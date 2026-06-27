import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.tools import (
    read_neo4j_cypher,
    get_current_time,
    send_slack_incident_alert,
)
from models.schema import (
    AnalyticsOutput,
    InfraTriageOutput,
    OnDemandLogsOutput,
    FinalRCAOutput,
    NotificationOutput,
)
from google.adk.agents import Agent
from google.adk.workflow import Workflow
from google.adk.events import Event

from agent.tools import check_pod_status_via_nats, fetch_pod_logs_via_nats
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
4. Extract the `failed_service` and `incident_id` from your session state. Also extract the Istio response flag (`dominant_flag`), HTTP/gRPC status code (`status_code`), `protocol`, `response_time`, `rates`, `flag_percent`, `is_mtls`, and `message` directly from the session state.
5. Analyze this incident data (like traffic rates, is_mtls, flag_percent, response_time, etc.) to deduce potential symptoms about the failed services. For example, check if traffic is dropping heavily, if mTLS is misconfigured, or if the failure rate is unusually high.
6. CRITICAL: Whenever an incident comes in, you MUST use the `get_current_time` tool to fetch the current date and time.
7. Append all these findings (including `failed_service`, `incident_id`, fetched timestamp, and deduced symptoms) into the structured AnalyticsOutput JSON.

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
    CASE WHEN size(upstream_services) > 0 THEN size(upstream_services) ELSE 1 END AS blast_radius
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
1. Check if `failed_pod` is empty (e.g., `""` or `"N/A"`). If it is empty, DO NOT use the `check_pod_status_via_nats` tool; proceed directly to step 3 assuming the pod does not exist. If a valid `failed_pod` is provided, use the `check_pod_status_via_nats` tool to fetch its status. You MUST also pass the `failed_service` as the `service_name` argument to the tool to fetch label matching and port details.
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
3. Determine if the failure is caused by resource exhaustion (memory/CPU limits), infrastructure scheduling issues, or if the pod does not exist. If the pod is "N/A - Pod not found", the deployment might be scaled to zero.
4. Set the `logs_required` boolean field appropriately. CRITICAL RULE: If the container reason is `Pending` or `FailedScheduling`, or if the pod is not found, or if there is a `service_match` failure (e.g., label selector mismatch or port mismatch), you DO NOT need to call the log agent, so set `logs_required` to False. If the reason is `CrashLoopBackOff`, `OOMKilled`, or anything related to the application crashing, set `logs_required` to True to fetch logs!
5. CRITICAL: You must include the exact `failed_pod` string in your output JSON so the downstream Logs Agent knows which pod to check! If it was empty, just output "N/A - Pod not found".

Do NOT investigate application code or mesh routing rules. Stick strictly to infrastructure state.
CRITICAL OUTPUT RULE: You MUST output ONLY valid JSON matching the InfraTriageOutput schema. Do not output conversational text or ask for more information.""",
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
2. If `logs_required` is explicitly False, DO NOT call your log fetching tools. Immediately output a message stating why logs were bypassed. (e.g., "Logs bypassed due to service/port mismatch" or "Deployment scaled to zero").
3. If `logs_required` is True (or missing), use the `fetch_pod_logs_via_nats` tool to fetch logs for the failed pod.
4. The log fetching tool returns data consisting of `PodName` and a `Logs` map.
5. Extract and analyze the logs to identify stack traces, application errors, or anomalies.
6. Summarize your findings into a concise report for the final RCA agent.""",
    tools=[fetch_pod_logs_via_nats],
    output_schema=OnDemandLogsOutput,
    output_key="on_demand_logs_output"
)  





final_rca_agent = Agent(
    name="final_rca_agent",
    description="Synthesizes all findings into the final Root Cause report.",
    instruction="""You are the Diagnostics / Final RCA Agent. You produce the definitive incident report.

## CRITICAL RULES - NEVER VIOLATE:
1. YOUR INPUT is a single massive JSON payload containing ALL previous agent outputs (`AnalyticsOutput`, `InfraTriageOutput`, `MeshConfigOutput`, `OnDemandLogsOutput`). USE ONLY THIS DATA!
2. DO NOT fabricate service names, resources, or conclusions that weren't in the input data.
3. ONLY cite evidence from the provided agent outputs.
4. DO NOT make up error messages, logs, or metrics.
5. You MUST include `failed_service` and `incident_id`. Extract them directly from the `AnalyticsOutput` block in your input JSON.
6. DO NOT SOLELY DEPEND ON LOGS. If `OnDemandLogsOutput` reports that logs are healthy/normal, but `InfraTriageOutput` or `MeshConfigOutput` reports a routing error (like a port mismatch or selector mismatch), then the root cause is the routing/infrastructure error, NOT the application! A service with broken routing will naturally have healthy logs because traffic never reaches it.

## Investigation Workflow:
1. Review the provided JSON for AnalyticsOutput (topology, blast radius), InfraTriageOutput (pod status, hypothesis), MeshConfigOutput, and OnDemandLogsOutput (log summary).
2. Extract conditions, errors, and relevant context directly from these inputs.
3. Formulate a cohesive root cause analysis based ONLY on the evidence. If the pod was not found (e.g. "N/A - Pod not found"), state clearly that the deployment might be scaled to zero. ONLY in this specific "scaled to zero" scenario, suggest checking the deployment replicas with `kubectl get deployment <failed_service> -n <namespace>` and scaling it up with `kubectl scale deployment <failed_service> --replicas=1 -n <namespace>` (Make sure to replace `<failed_service>` with the actual `failed_service` value from AnalyticsOutput). For all other issues, suggest standard remediation like `kubectl rollout restart`.

## STRUCTURED OUTPUT:
You MUST return a JSON object matching the FinalRCAOutput schema, including `failed_service` and `incident_id`.

CRITICAL FOR CITATIONS:
- snippet MUST ALWAYS be a dictionary/object { }, NEVER a string.
- Each citation must have: node_key, snippet (dict), and source.

Examples of VALID snippet objects:
1. From analytics_agent:      {"blast_radius": 5, "failed_pod": "frontend-xyz"}
2. From infra_workload_agent: {"pod_status": "CrashLoopBackOff", "hypothesis": "OOMKilled"}
3. From on_demand_logs_agent: {"logs_summary": "Found NullPointerException at line 42"}

DO NOT:
- Create empty or null snippets
- Pass raw text blocks as a string inside the snippet
- Omit the source field
- Make up data that wasn't in the input from the agents""",
    output_schema=FinalRCAOutput,
    output_key="final_rca_output"
)

notification_agent = Agent(
    name="notification_agent",
    description="Posts RCA incident card to Slack.",
    instruction="""You are the Notification Agent. You post the final RCA incident card to Slack via a Webhook.
You run AFTER the Final RCA Agent so the complete report is shared with the team.

YOUR INPUT is a pre-formatted JSON payload that perfectly matches the arguments for the `send_slack_incident_alert` tool.

YOUR JOB:
1. Call the `send_slack_incident_alert` tool immediately using EXACTLY the 12 fields provided in YOUR INPUT. Do not change, omit, or fabricate anything.
2. Return a JSON object matching NotificationOutput.

CRITICAL RULES:
- Pass the arguments exactly as they appear in the JSON payload.""",
    tools=[send_slack_incident_alert],
    output_schema=NotificationOutput,
    output_key="notification_output"
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

def send_notification_action(final_rca_output: FinalRCAOutput, ctx: InvocationContext):
    """Executes the Slack notification deterministically in Python, bypassing the LLM entirely."""
    import json
    from datetime import datetime
    
    analytics = ctx.state.get("analytics_triage_output", {})
    
    blast_radius = analytics.get("blast_radius", 1)
    if blast_radius > 3:
        severity = "critical"
    elif blast_radius > 1:
        severity = "high"
    else:
        severity = "medium"
        
    upstream = analytics.get("upstream_failed_services", [])
    downstream = analytics.get("downstream_failed_services", [])
    impacted = upstream + downstream
    impacted_str = ",".join(impacted) if impacted else "None"
    
    commands = final_rca_output.remediation_plan.kubectl_commands
    kubectl_command = commands[0] if commands else "None"
    
    if "N/A - Pod not found" in final_rca_output.diagnosis_summary or "scaled to zero" in final_rca_output.suspected_root_cause:
        fs = analytics.get("failed_service", "unknown")
        kubectl_command = f"kubectl scale deployment {fs} --replicas=1 -n default"
        
    timestamp = analytics.get("timestamp", "")
    if not timestamp:
        timestamp = datetime.utcnow().isoformat()
    
    slack_payload = {
        "incident_id": analytics.get("incident_id", final_rca_output.incident_id or "unknown"),
        "failed_service": analytics.get("failed_service", final_rca_output.failed_service or "unknown"),
        "failed_pod": analytics.get("failed_pod", "unknown") or "unknown",
        "root_cause": final_rca_output.suspected_root_cause,
        "diagnosis_summary": final_rca_output.diagnosis_summary,
        "evidence": "\n".join(final_rca_output.observed_conditions),
        "impacted_services": impacted_str,
        "blast_radius": blast_radius,
        "severity": severity,
        "kubectl_command": kubectl_command,
        "timestamp": timestamp,
        "namespace": "default"
    }
    
    print("Executing Slack webhook directly from Python...")
    
    # Call the tool directly in Python
    from agent.tools import send_slack_incident_alert
    result_str = send_slack_incident_alert(**slack_payload)
    
    try:
        res_dict = json.loads(result_str)
    except Exception:
        res_dict = {"status": "error", "error": result_str}
        
    is_success = res_dict.get("status") == "success"
    
    # Return the final schema output
    notif_out = NotificationOutput(
        slack_message_sent=is_success,
        incident_id=slack_payload["incident_id"],
        kubectl_command=slack_payload["kubectl_command"],
        error=res_dict.get("error"),
        slack_channel=res_dict.get("channel")
    )
    
    # Emitting the Event with the output directly terminates this pipeline branch
    return notif_out

def prepare_final_rca_data(ctx: InvocationContext):
    """Aggregates all prior outputs and feeds them into the final RCA LLM."""
    import json
    
    analytics_data = ctx.state.get("analytics_triage_output", {})
    infra_data = ctx.state.get("infra_triage_output", {})
    mesh_data = ctx.state.get("mesh_config_output", {})
    logs_data = ctx.state.get("on_demand_logs_output", {})
    
    if hasattr(logs_data, 'model_dump'):
        logs_data = logs_data.model_dump()
    
    consolidated_payload = {
        "AnalyticsOutput": analytics_data,
        "InfraTriageOutput": infra_data,
        "MeshConfigOutput": mesh_data,
        "OnDemandLogsOutput": logs_data
    }
    
    payload_str = json.dumps(consolidated_payload, indent=2)
    print(f"Aggregated data for Final RCA Agent:\n{payload_str}")
    
    return Event(route="RUN_FINAL_RCA", data=payload_str)

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

        # Aggregate all state data for the Final RCA Agent
        (on_demand_logs_agent, prepare_final_rca_data),
        (prepare_final_rca_data, {
            "RUN_FINAL_RCA": final_rca_agent
        }),

        # Replace Notification Agent LLM entirely and execute in Python
        (final_rca_agent, send_notification_action)
    ]
)

# The Workflow itself is the executable pipeline
main_agent = rca_orchestrator
root_agent = main_agent


   
