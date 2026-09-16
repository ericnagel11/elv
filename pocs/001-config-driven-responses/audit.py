"""Query the App Configuration audit trail from Log Analytics.

Two resource-log tables answer different governance questions:

  AACAudit       data-plane write operations, not aggregated, and it carries
                 CallerIdentity, so it answers "who changed what".
  AACHttpRequest reads and writes, aggregated, and it carries StatusCode, so it
                 is where a denied (403) attempt shows up.

The Azure activity log is not sufficient here: it records control-plane
operations only and does not capture key-value reads or writes.

VM queries use a dedicated managed identity and resource context for the two
App Configuration stores. Outside VM mode, queries use the developer credential
and configured workspace. Query scope does not replace Azure access controls.
"""

import os

from azure.monitor.query import LogsQueryClient, LogsQueryStatus

import hosting
import rbac

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


def workspace_configured() -> bool:
    return bool(os.environ.get(WORKSPACE_ENV))


def run_query(query: str):
    """Run a KQL query and return (columns, rows). Raises on query failure."""
    client = LogsQueryClient(rbac.service_credential("audit"))
    if hosting.vm_mode():
        columns, rows = [], []
        for resource_id in hosting.audit_resource_ids():
            response = client.query_resource(resource_id=resource_id, query=query, timespan=None)
            resource_columns, resource_rows = _query_result(response)
            if resource_columns:
                if columns and columns != resource_columns:
                    raise RuntimeError("The two resource log schemas do not match.")
                columns = resource_columns
                rows.extend(resource_rows)
        # Each canned query projects TimeGenerated first and already limits its
        # own resource results. Merge both without hiding the newest event.
        return columns, sorted(rows, key=lambda row: str(row[0]), reverse=True)[:50]
    response = client.query_workspace(
        workspace_id=os.environ[WORKSPACE_ENV], query=query, timespan=None
    )
    return _query_result(response)


def _query_result(response):
    status = getattr(response, "status", LogsQueryStatus.SUCCESS)
    if hosting.vm_mode() and status != LogsQueryStatus.SUCCESS:
        raise RuntimeError("Audit query incomplete; verify resource-log access and diagnostics.")
    if status == LogsQueryStatus.FAILURE:
        raise RuntimeError(getattr(response, "partial_error", "The log query failed."))

    # A successful result exposes .tables; a partial result exposes .partial_data.
    tables = getattr(response, "tables", None) or getattr(response, "partial_data", None) or []
    if not tables:
        return [], []
    table = tables[0]
    return list(table.columns), [list(row) for row in table.rows]
