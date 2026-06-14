from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class DestService(BaseModel):
    cluster: str
    namespace: str
    name: str

class Traffic(BaseModel):
    protocol: str
    rates: Dict[str, str]

class Containers(BaseModel):
    containerName: Optional[str] = None
    logs: Optional[str] = None
    status: Optional[str] = None
    reason: Optional[str] = None
    exitCode: Optional[int] = None

class Pods(BaseModel):
    name: str
    status: str
    container: List[Containers]
    StatusMessage: Optional[str] = None

class NodeData(BaseModel):
    id: str
    nodeType: str
    cluster: str
    namespace: str
    app: str
    destServices: Optional[List[DestService]] = None
    traffic: Optional[List[Traffic]] = None
    healthData: Optional[Any] = None
    isRoot: Optional[bool] = None
    pod: Optional[List[Pods]] = None

class Node(BaseModel):
    data: NodeData

class ResponseDetail(BaseModel):
    flags: Dict[str, str]
    hosts: Dict[str, str]

class EdgeTraffic(BaseModel):
    protocol: str
    rates: Dict[str, str]
    responses: Dict[str, ResponseDetail]

class EdgeData(BaseModel):
    id: str
    source: str
    target: str
    destPrincipal: str
    sourcePrincipal: str
    isMTLS: str
    responseTime: Optional[str] = None
    throughput: Optional[str] = None
    traffic: EdgeTraffic

class Edge(BaseModel):
    data: EdgeData

class Elements(BaseModel):
    nodes: List[Node]
    edges: List[Edge]

class GraphResponse(BaseModel):
    timestamp: int
    duration: int
    graphType: str
    elements: Elements

class PodAlert(BaseModel):
    incidentId: str
    podName: str
    namespace: str
    app: str
    status: str
    statusMessage: Optional[str] = None
    reason: Optional[str] = None
    timestamp: int

class TrafficAlert(BaseModel):
    incidentId: str
    source: str
    target: str
    responseCode: str
    flag: str
    host: Optional[str] = None
    protocol: Optional[str] = None
    responseTime: Optional[str] = None
    rates: Optional[Dict[str, str]] = None
    flagPercent: Optional[str] = None
    isMTLS: Optional[str] = None
    message: str
    timestamp: int

class AnalyticsOutput(BaseModel):
    upstream_failed_services: List[str] = Field(description="List of upstream services impacted by this failure.")
    downstream_failed_services: List[str] = Field(description="List of downstream services impacted by this failure.")
    blast_radius: int = Field(description="The count of services dependent on this failed service.")
    failed_pod: str = Field(description="The specific pod that failed. Do not include pods from other services. For example if failed service is frontend, the pod should be like frontend-849f6b48f8-v6j2q.")
    timestamp: str = Field(description="The current timestamp (date and time) of the analysis.")
    protocol: Optional[str] = Field(description="Traffic protocol (e.g., http, grpc).", default=None)
    response_time: Optional[str] = Field(description="Response time of the failed request.", default=None)
    rates: Optional[Dict[str, str]] = Field(description="Traffic rates (http, grpc, etc.).", default=None)
    flag_percent: Optional[str] = Field(description="Percentage of requests with this flag.", default=None)
    is_mtls: Optional[str] = Field(description="Whether mTLS is enabled.", default=None)
    message: Optional[str] = Field(description="Detailed traffic failure message.", default=None)
    status_code: Optional[str] = Field(description="HTTP or gRPC status code.", default=None)
    symptoms: Optional[str] = Field(description="Deduced symptoms about failed services based on incident data like traffic rates, mTLS, and flag percent.", default=None)

class InfraTriageOutput(BaseModel):
    failed_pod: str = Field(description="The name of the pod being investigated. Passed down for the log agent to use.")
    pod_status: str = Field(description="The current state of the pod (e.g. CrashLoopBackOff, OOMKilled, ScaledToZero, or Unknown)")
    infrastructure_hypothesis: str = Field(description="The agent's hypothesis on why the pod is in this state.")
    logs_required: bool = Field(description="True if application logs are needed to investigate further, False if it's a pure infrastructure issue like Node failure or Scale to Zero.")



class OnDemandLogsOutput(BaseModel):
    pod_name: str = Field(description="The name of the pod whose logs were fetched.")
    logs_summary: str = Field(description="A concise summary and analysis of the fetched logs, highlighting any stack traces, errors, or anomalies.")

class RemediationOutput(BaseModel):
    immediate_actions: List[str] = Field(description="Immediate steps to mitigate the issue")
    long_term_fixes: List[str] = Field(description="Long-term recommendations to prevent recurrence")
    kubectl_commands: List[str] = Field(description="Safe kubectl commands to apply the fix")

class FinalRCAOutput(BaseModel):
    observed_conditions: List[str] = Field(description="Conditions observed across all agent outputs")
    diagnosis_summary: str = Field(description="Summary of findings")
    suspected_root_cause: str = Field(description="Your root cause analysis")
    investigation_complete: bool = Field(description="Whether investigation is complete")
    remediation_plan: RemediationOutput = Field(description="The proposed remediation plan")