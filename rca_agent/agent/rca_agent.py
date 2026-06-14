import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.tools import read_neo4j_cypher, get_current_time
from models.schema import AnalyticsOutput, InfraTriageOutput, OnDemandLogsOutput, FinalRCAOutput, RemediationOutput
from google.adk.agents import Agent
from google.adk.workflow import Workflow
from google.adk.events import Event

from agent.tools import check_pod_status_via_nats, fetch_pod_logs_via_nats, send_email_via_gmail
from google.adk.agents.invocation_context import InvocationContext



SYSTEM_INSTRUCTION = """
YOU ARE A SMART RCA ORCHESTRATOR YOUR JOB IS TO JUST ORCHESTRATE RCA PIPELINE 
INSTRUCTIONS: WHEN YOU RECEIVE AN ALERT YOUR JOB IS TO PASS THE OUTPUT OF EACH SEQUENTIL AGENT TO ANOTHER
DO NOT:
- Analyze the incident yourself
- Generate any RCA content
- Use any tools (incident data is already parsed and available in session state)
- Provide final responses

DO:
- Transfer immediately to RCA_Pipeline
- Let RCA_Pipeline handle everything

The RCA_Pipeline sub-agent will provide the final RCA response.
"""



analytics_agent = Agent( 
    name="analytics_agent",

    description="Analyzes the infrastructure topology and Istio metrics to categorize the incident.",
    instruction="""
    You are the Analytics Agent.

You are executed immediately when a traffic alert is received. The traffic alert data including `failed_service`, `dominant_flag`, `status_code`, `protocol`, `response_time`, `rates`, `flag_percent`, `is_mtls`, and `message` are saved in your session state. You MUST extract these details from your session state before running any queries.

Your responsibility is to:
1. Identify the specific failed pod associated with the failed service using Neo4j topology. Do NOT consider pods from other services. For example, if the failed service is `frontend`, the failed pod should look like `frontend-849f6b48f8-v6j2q`.
2. Determine upstream and downstream dependent services using Neo4j topology.
3. Calculate blast radius.
4. Extract the Istio response flag (`dominant_flag`), HTTP/gRPC status code (`status_code`), `protocol`, `response_time`, `rates`, `flag_percent`, `is_mtls`, and `message` directly from the session state.
5. Analyze this incident data (like traffic rates, is_mtls, flag_percent, response_time, etc.) to deduce potential symptoms about the failed services. For example, check if traffic is dropping heavily, if mTLS is misconfigured, or if the failure rate is unusually high.
6. CRITICAL: Whenever an incident comes in, you MUST use the `get_current_time` tool to fetch the current date and time.
7. Append all these findings, including the fetched timestamp and deduced symptoms, into the structured AnalyticsOutput JSON.

STRICT EXECUTION RULES:

- You MUST use ONLY the provided Cypher queries.
- You MUST use ONLY the `read_neo4j_cypher` tool for topology analysis.
- DO NOT generate custom queries.
- DO NOT modify relationship names.
- DO NOT hallucinate services, dependencies, or metrics.
- DO NOT infer topology outside graph results.
- DO NOT output explanations, markdown, reasoning, or commentary.
- Output MUST be ONLY strict JSON matching the AnalyticsOutput schema.
- If query results are empty, return empty arrays and default values.

AVAILABLE GRAPH RELATIONSHIPS:

(Service)-[:HAS_POD]->(Pod)

(Service)-[:TRAFFIC_TO]->(Service)

Relationship meaning:
- HAS_POD → service owns/routes to pod
- TRAFFIC_TO → source service sends traffic to destination service

The failed service is available in your session state under `failed_service`. You MUST read the failed service from your session state and substitute `$failed_service` with its value in the queries below.

TASK 1 — FIND FAILED PODS

Use ONLY this exact Cypher query to find the pod associated with the failed service:

```cypher
MATCH (s:Service)-[:HAS_POD]->(p:Pod)
WHERE s.app = $failed_service
RETURN p.name AS failed_pod LIMIT 1
```

TASK 2 — FIND UPSTREAM/DOWNSTREAM SERVICES AND BLAST RADIUS

Use ONLY this exact Cypher query:

```cypher
MATCH (failed:Service)
WHERE failed.app = $failed_service
OPTIONAL MATCH (up:Service)-[:TRAFFIC_TO]->(failed)
WITH failed, collect(DISTINCT up.app) AS upstream_services
OPTIONAL MATCH (failed)-[:TRAFFIC_TO]->(down:Service)
RETURN
    upstream_services,
    collect(DISTINCT down.app) AS downstream_services,
    size(upstream_services) AS blast_radius  
```
    

TASK 3 — SYMPTOM ANALYSIS

Analyze the incident data from your session state to deduce symptoms. Use these guidelines:
- If `is_mtls` is missing or mismatched and `status_code` indicates a 503 or TLS error, symptom is likely "mTLS configuration mismatch or certificate issue".
- If `flag_percent` is high (e.g. 100%), symptom is "High percentage of traffic is failing".
- If `rates` (like HTTP/gRPC requests per second) drop near 0 or are unexpectedly low, symptom is "Traffic is not reaching the destination (Idle or Blocked)".
- If `rates` show an unusually high volume of requests, symptom could be "Service is experiencing a traffic spike or overload".
- If `dominant_flag` is "UH" (No healthy upstream) or "UF" (Upstream connection failure), symptom is "Upstream service is unreachable or crashed".
- If `dominant_flag` is "NR" (No route configured), symptom is "Istio routing configuration is missing or invalid".
- If `response_time` is unusually high along with timeout flags, symptom is "Service degradation or cascading latency".
Compile your findings into a clear statement for the `symptoms` field.

CRITICAL: You MUST execute Tasks 1 and 2 sequentially using your Cypher tool, and perform Task 3 by analyzing your session state BEFORE generating your final JSON response. Do not skip any task.
""",
    tools=[read_neo4j_cypher, get_current_time],
    output_schema=AnalyticsOutput,
    output_key="analytics_triage_output"
)

# --- Sub-Agents for Routing ---
infra_workload_agent = Agent(
    name="infra_workload_agent", 
    description="Investigates infrastructure and node health.",
    instruction="""You are the Infrastructure Workload Agent.
EXECUTION TRIGGER: You were triggered because Istio detected a UH, UF, or UC connection failure flag.

Your input data contains the `failed_pod` and `failed_service`. The pod name is ALWAYS provided from the analytics output.

YOUR JOB:
1. Use the `check_pod_status_via_nats` tool to fetch the status of the `failed_pod`.
2. Analyze the pod status data returned. The data will look like this mock structure:
{
  "pod_name": "frontend-xyz",
  "phase": "Pending",
  "container_statuses": [
    {
      "name": "frontend",
      "state": "waiting",
      "reason": "CrashLoopBackOff",
      "restart_count": 5,
      "exit_code": 137
    }
  ],
  "recent_events": [
    {
      "reason": "FailedScheduling",
      "message": "0/3 nodes are available: 3 Insufficient memory."
    }
  ]
}
3. Determine if the failure is caused by resource exhaustion (memory/CPU limits) or infrastructure scheduling issues.
4. Set the `logs_required` boolean field appropriately. CRITICAL RULE: If the container reason is `Pending`, `OOMKilled`, or `CrashLoopBackOff`, you DO NOT need to call the log agent, so set `logs_required` to False. Otherwise, set it to True.
5. CRITICAL: You must include the exact `failed_pod` string in your output JSON so the downstream Logs Agent knows which pod to check!

Do NOT investigate application code or mesh routing rules. Stick strictly to infrastructure state.""",
    tools=[check_pod_status_via_nats],
    output_schema=InfraTriageOutput,
    output_key="infra_triage_output"
)

mesh_config_agent = Agent(
    name="mesh_config_agent", 
    description="Investigates Istio and Kubernetes routing configurations.",
    instruction="""You are the Mesh Configuration Agent.
EXECUTION TRIGGER: Executed when Istio routing failures (flags: NR, NC) are detected.
YOUR JOB: Analyze Istio VirtualServices, DestinationRules, and Kubernetes Services to find misconfigurations preventing traffic routing."""
)



# --- Secondary Pipeline Agents ---
on_demand_logs_agent = Agent(
    name="on_demand_logs_agent",
    description="Fetches application or system logs on demand.",
    instruction="""You are the On-Demand Logs Agent.
EXECUTION TRIGGER: You receive input from the previous triage agents (e.g., infra_workload_agent).
YOUR JOB: 
1. Check your input data for the `logs_required` boolean field.
2. If `logs_required` is explicitly False, DO NOT call your log fetching tools. Immediately output a message stating that logs were bypassed due to a pure infrastructure failure.
3. If `logs_required` is True (or missing), use the `fetch_pod_logs_via_nats` tool to fetch logs for the failed pod.
4. The log fetching tool returns data consisting of `PodName` and a `Logs` map (a dictionary mapping container names to their respective log strings).
5. Extract and analyze the logs from this map to identify stack traces, application errors, or anomalies correlating with the incident.
6. Summarize your findings into a concise report for the final RCA agent.""",
    tools=[fetch_pod_logs_via_nats],
    output_schema=OnDemandLogsOutput,
    output_key="on_demand_logs_output"
)  





final_rca_agent = Agent(
    name="final_rca_agent",
    description="Synthesizes all findings into the final Root Cause report.",
    instruction="""You are the Diagnostics / Final RCA Agent. Your job is to perform a deep investigation of the incident based on the outputs from the previous agents.

## CRITICAL RULES - NEVER VIOLATE:
1. USE ONLY DATA FROM the previous agent outputs (AnalyticsOutput, InfraTriageOutput, OnDemandLogsOutput).
2. DO NOT fabricate service names, resources, or conclusions that weren't in the input data.
3. ONLY cite evidence from the provided agent outputs - DO NOT create fictional citations.
4. DO NOT make up error messages, logs, or metrics. Base conclusions ONLY on actual evidence provided by the triage and analytics agents.

## Investigation Workflow:
1. Review the AnalyticsOutput (topology, blast radius), InfraTriageOutput (pod status, hypothesis), and OnDemandLogsOutput (log summary) provided to you.
2. Extract conditions, errors, and relevant context directly from these inputs.
3. Formulate a cohesive root cause analysis based ONLY on the evidence.
4. Provide structured citations pointing to the specific agent that supplied the evidence.

## STRUCTURED OUTPUT:
You MUST return a JSON object matching the FinalRCAOutput schema.

CRITICAL FOR CITATIONS:
- snippet MUST ALWAYS be a dictionary/object { }, NEVER a string.
- Extract structured fields rather than including raw text blocks.
- Each citation must have: `node_key` (e.g., the failed pod or service name), `snippet` (dict), and `source` (e.g., "analytics_agent", "infra_workload_agent", or "on_demand_logs_agent").

Examples of VALID snippet objects based on your input schemas:
1. From analytics_agent: {"blast_radius": 5, "failed_pod": "frontend-xyz", "upstream_services": ["gateway"]}
2. From infra_workload_agent: {"pod_status": "CrashLoopBackOff", "hypothesis": "OOMKilled due to memory limit"}
3. From on_demand_logs_agent: {"logs_summary": "Found NullPointerException at line 42 in PaymentService"}

DO NOT:
- Create empty or null snippets
- Pass raw text blocks as a string inside the snippet
- Omit the source field
- Make up data that wasn't in the input from the agents""",
    output_schema=FinalRCAOutput,
    output_key="final_rca_output"
)

remediation_agent = Agent(

    name="remediation_agent",
    description="Suggests remediation steps based on the RCA findings.",
    instruction="""You are the Remediation Agent. Your job is to take the evidence gathered by the diagnostic agents and propose concrete fixes.

YOUR INPUT: The outputs from the previous triage agents (AnalyticsOutput, InfraTriageOutput, OnDemandLogsOutput).

YOUR JOB:
1. Analyze the observed conditions and errors from the diagnostic inputs.
2. Formulate a hypothetical root cause based on the data.
3. Determine immediate actions required to mitigate the issue (e.g., restart pod, scale up).
4. Determine long term fixes to prevent recurrence (e.g., increase memory limits, add retry logic).
5. Provide safe kubectl commands that an SRE could run to apply the fix.

You MUST return a JSON object matching the RemediationOutput schema.""",
    output_schema=RemediationOutput,
    output_key="remediation_output"
)

gmail_agent = Agent(
    name="gmail_agent",
    description="Sends the final RCA report to Gmail.",
    instruction="""You are the Gmail Agent.
EXECUTION TRIGGER: You are the absolute last step.
YOUR JOB: Format the final RCA report into a clear string representation and use the `send_email_via_gmail` tool to email it to the configured recipient. Provide the tool output as your final response.""",
    tools=[send_email_via_gmail]
)

def flag_router(analytics_triage_output: AnalyticsOutput, ctx: InvocationContext):
    """Route to the correct specialized agent based on Istio response flags."""
    
    # Extract from session state
    dominant_flag = ctx.state.get('dominant_flag', 'none')
    failed_service = ctx.state.get('failed_service', 'unknown')
    
    output_lower = str(dominant_flag).lower()
    print(f"Routing logic for failed service '{failed_service}' based on flag '{dominant_flag}'")
    
    # We pass the analytics output forward to the next agent as data
    if "uh" in output_lower or "uf" in output_lower or "uc" in output_lower:
        return Event(route="RUN_INFRA_AGENT", data=analytics_triage_output)
    elif "nr" in output_lower or "nc" in output_lower:
        return Event(route="RUN_CONFIG_AGENT", data=analytics_triage_output)
    else:
        # Default to checking application if it's a 5xx error or rate limit
        return Event(route="RUN_APP_AGENT", data=analytics_triage_output)

rca_orchestrator = Workflow( 
    name="rca_orchestrator",
    description="RCA Pipeline Orchestrator",
    edges=[
        ("START", analytics_agent),
        # (infra_topology_agent, analytics_agent),
        
        # Branch based on Analytics findings
        (analytics_agent, flag_router),
        (flag_router, {
            "RUN_INFRA_AGENT": infra_workload_agent,
            "RUN_CONFIG_AGENT": mesh_config_agent,
        }),  
        
        # Converge back to the next stage in the pipeline
        (infra_workload_agent, on_demand_logs_agent),
        (mesh_config_agent, on_demand_logs_agent),
        
        # Finish the pipeline
        (on_demand_logs_agent, remediation_agent),
        (remediation_agent, final_rca_agent),
        (final_rca_agent, gmail_agent)
    ]
)

# The Workflow itself is the executable pipeline
main_agent = rca_orchestrator
root_agent = main_agent


   
