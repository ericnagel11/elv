"""Query the App Configuration audit trail from Log Analytics.

Two resource-log tables answer different governance questions:

  AACAudit       data-plane write operations, not aggregated, and it carries
                 CallerIdentity, so it answers "who changed what".
  AACHttpRequest reads and writes, aggregated, and it carries StatusCode, so it
                 is where a denied (403) attempt shows up.

The Azure activity log is not sufficient here: it records control-plane
operations only and does not capture key-value reads or writes.

One query is specific to this proof of concept. Because a market is a label and
the certification gate is a key, a change to what a market may draw on appears
in AACAudit like any other write. That is the whole answer to "who decided that
machine-translated content could answer German customers, and when".

Queries run under the signed-in developer credential rather than a persona, so
the demonstration does not need Log Analytics Reader granted to every service
principal.
"""

import os

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

WORKSPACE_ENV = "AZURE_LOG_ANALYTICS_WORKSPACE_ID"

CHANGES_QUERY = """
AACAudit
| where TimeGenerated > ago(1d)
| where OperationName in ("set-keyvalue", "delete-keyvalue")
| project TimeGenerated, OperationName, TargetResource, CallerIdentity, CallerIPAddress
| sort by TimeGenerated desc
| take 50
"""

DENIED_QUERY = """
AACHttpRequest
| where TimeGenerated > ago(1d)
| where StatusCode == "403"
| project TimeGenerated, Method, RequestURI, StatusCode, ClientObjectId, HitCount
| sort by TimeGenerated desc
| take 50
"""

GATE_QUERY = """
AACAudit
| where TimeGenerated > ago(7d)
| where OperationName in ("set-keyvalue", "delete-keyvalue")
| where TargetResource has "translation_gate" or TargetResource has "disclosure_set"
| project TimeGenerated, OperationName, TargetResource, CallerIdentity, CallerIPAddress
| sort by TimeGenerated desc
| take 50
"""


def workspace_configured() -> bool:
    return bool(os.environ.get(WORKSPACE_ENV))


def run_query(query: str):
    """Run a KQL query and return (columns, rows). Raises on query failure."""
    workspace_id = os.environ[WORKSPACE_ENV]
    client = LogsQueryClient(DefaultAzureCredential())
    response = client.query_workspace(workspace_id=workspace_id, query=query, timespan=None)

    status = getattr(response, "status", LogsQueryStatus.SUCCESS)
    if status == LogsQueryStatus.FAILURE:
        raise RuntimeError(getattr(response, "partial_error", "The log query failed."))

    # A successful result exposes .tables; a partial result exposes .partial_data.
    tables = getattr(response, "tables", None) or getattr(response, "partial_data", None) or []
    if not tables:
        return [], []
    table = tables[0]
    return list(table.columns), [list(row) for row in table.rows]
