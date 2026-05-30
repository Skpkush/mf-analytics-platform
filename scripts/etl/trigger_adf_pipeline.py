#!/usr/bin/env python3
"""
trigger_adf_pipeline.py
Trigger an ADF pipeline run and poll until completion.

Auth: InteractiveBrowserCredential — opens your default browser for
Azure AD login. No service principal or CLI required.

Auto-discovers:
  - Subscription ID  (first subscription on the account)
  - ADF factory name (first factory in rg-mf-analytics)

Usage:
    python scripts/etl/trigger_adf_pipeline.py
    python scripts/etl/trigger_adf_pipeline.py --table Fact_NAV --blob nav_yahoo_clean_20260529.parquet
    python scripts/etl/trigger_adf_pipeline.py --table Dim_AMC --pre-script "TRUNCATE TABLE dbo.Dim_AMC"
"""
from __future__ import annotations

import argparse
import logging
import time

from azure.identity import InteractiveBrowserCredential
from azure.mgmt.datafactory import DataFactoryManagementClient
from azure.mgmt.subscription import SubscriptionClient

RESOURCE_GROUP = "rg-mf-analytics"
PIPELINE_NAME  = "pl_raw_to_sql"
POLL_INTERVAL  = 10   # seconds between status checks
MAX_WAIT_SEC   = 600  # 10-minute timeout

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("adf_trigger")


def get_subscription_id(credential) -> str:
    sub_client = SubscriptionClient(credential)
    subs = list(sub_client.subscriptions.list())
    if not subs:
        raise RuntimeError("No Azure subscriptions found on this account.")
    if len(subs) > 1:
        log.info("Multiple subscriptions found — using the first:")
        for s in subs:
            log.info(f"  {s.subscription_id}  {s.display_name}")
    sub = subs[0]
    log.info(f"Subscription: {sub.display_name} ({sub.subscription_id})")
    return sub.subscription_id


def get_factory_name(adf_client: DataFactoryManagementClient) -> str:
    factories = list(adf_client.factories.list_by_resource_group(RESOURCE_GROUP))
    if not factories:
        raise RuntimeError(
            f"No ADF factory found in resource group '{RESOURCE_GROUP}'.\n"
            "Make sure you created the ADF instance in the portal first."
        )
    factory = factories[0]
    log.info(f"ADF factory: {factory.name}")
    return factory.name


def trigger_and_poll(
    adf_client: DataFactoryManagementClient,
    factory_name: str,
    table_name: str,
    blob_path: str,
    pre_script: str,
) -> None:
    params = {
        "p_table_name":      table_name,
        "p_blob_path":       blob_path,
        "p_pre_copy_script": pre_script,
    }

    log.info("─" * 55)
    log.info(f"Pipeline      : {PIPELINE_NAME}")
    log.info(f"p_table_name  : {table_name}")
    log.info(f"p_blob_path   : {blob_path}")
    log.info(f"p_pre_script  : {pre_script or '(none)'}")
    log.info("─" * 55)

    run_response = adf_client.pipelines.create_run(
        resource_group_name=RESOURCE_GROUP,
        factory_name=factory_name,
        pipeline_name=PIPELINE_NAME,
        parameters=params,
    )
    run_id = run_response.run_id
    log.info(f"Run triggered  — run_id: {run_id}")

    # ── Poll until terminal state ────────────────────────────────────────
    terminal = {"Succeeded", "Failed", "Cancelled"}
    elapsed  = 0

    while elapsed < MAX_WAIT_SEC:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        run = adf_client.pipeline_runs.get(RESOURCE_GROUP, factory_name, run_id)
        status = run.status
        log.info(f"  [{elapsed:>3}s]  status: {status}")

        if status in terminal:
            break

    # ── Final result ─────────────────────────────────────────────────────
    log.info("─" * 55)
    if status == "Succeeded":
        # Pull copy-activity output for row counts
        acts = list(adf_client.activity_runs.query_by_pipeline_run(
            resource_group_name=RESOURCE_GROUP,
            factory_name=factory_name,
            run_id=run_id,
            filter_parameters={"lastUpdatedAfter": run.run_start, "lastUpdatedBefore": run.run_end},
        ).value)

        for act in acts:
            output = act.output or {}
            log.info(
                f"PASSED  {act.activity_name}\n"
                f"        rows read    : {output.get('rowsRead',    'n/a')}\n"
                f"        rows written : {output.get('rowsCopied',  'n/a')}\n"
                f"        duration     : {output.get('copyDuration','n/a')}s\n"
                f"        throughput   : {output.get('throughput',  'n/a')} KB/s"
            )
    elif status == "Failed":
        acts = list(adf_client.activity_runs.query_by_pipeline_run(
            resource_group_name=RESOURCE_GROUP,
            factory_name=factory_name,
            run_id=run_id,
            filter_parameters={"lastUpdatedAfter": run.run_start, "lastUpdatedBefore": run.run_end},
        ).value)
        for act in acts:
            if act.status == "Failed":
                err = act.error or {}
                log.error(f"FAILED  {act.activity_name}: {err.get('message', 'unknown error')}")
    else:
        log.warning(f"Run ended with status: {status}")

    log.info("─" * 55)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger ADF pl_raw_to_sql pipeline run")
    parser.add_argument("--table",      default="Dim_AMC",
                        help="Target SQL table (default: Dim_AMC)")
    parser.add_argument("--blob",       default="nav_amfi_clean_20260529.parquet",
                        help="Blob filename in processed/ container")
    parser.add_argument("--pre-script", default="TRUNCATE TABLE dbo.Dim_AMC",
                        help="T-SQL to run before copy (default: TRUNCATE TABLE dbo.Dim_AMC)")
    args = parser.parse_args()

    log.info("Opening browser for Azure AD login...")
    credential = InteractiveBrowserCredential()

    sub_id     = get_subscription_id(credential)
    adf_client = DataFactoryManagementClient(credential, sub_id)
    factory    = get_factory_name(adf_client)

    trigger_and_poll(
        adf_client   = adf_client,
        factory_name = factory,
        table_name   = args.table,
        blob_path    = args.blob,
        pre_script   = args.pre_script,
    )


if __name__ == "__main__":
    main()
