import os
import time
import logging
from time import sleep

import pandas as pd

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

from prometheus_api_client import PrometheusConnect
import metric_restructurers


# Set up logging
_LOGGER = logging.getLogger(__name__)

if os.getenv("FLT_DEBUG_MODE","False") == "True":
    logging_level = logging.DEBUG # Enable Debug mode
else:
    logging_level = logging.INFO

# Log record format
# TODO: add module name
logging.basicConfig(format='%(asctime)s:%(levelname)s: %(message)s', level=logging_level)


def update_saved_prom_metrics(metrics, save_dir):
    # connect to prometheus
    pc = PrometheusConnect(
        url="https://telemeter-lts.datahub.redhat.com/",
        headers={"Authorization": "bearer InsertTokenHere"},
        disable_ssl=True,
    )

    # get metrics if avaiable
    if "cluster_operator_conditions" in metrics:
        conditions_df = metric_preprocessors.opconds_metrics_to_df(
            metrics_raw=pc.get_current_metric_value("cluster_operator_conditions")
        )
    if "cluster_installer" in metrics:
        install_df = metric_preprocessors.installer_metrics_to_df(
            metrics_raw=pc.get_current_metric_value("cluster_installer")
        )
    if "cluster_version" in metrics:
        versions_df = metric_preprocessors.version_metrics_to_df(
            metrics_raw=pc.get_current_metric_value("cluster_version")
        )

    # combine all metrics
    metrics_df = conditions_df.merge(install_df, how="left", left_index=True, right_index=True)
    metrics_df = metrics_df.merge(versions_df, how="left", left_index=True, right_index=True)

    # nans because some install types are neither upi nor ipi (unknown)
    metrics_df["install_type_IPI"] = metrics_df["install_type_IPI"].fillna(0)
    metrics_df["install_type_UPI"] = metrics_df["install_type_UPI"].fillna(0)

    # save to volume
    metrics_df.to_parquet(
        fname=os.path.join(save_dir, "metrics.parquet"),
        engine="pyarrow",
        index=True,
    )


def main():
    # get prometheus metrics defined in env var FLT_METRICS_LIST
    metrics_list = os.getenv("FLT_METRICS_LIST")
    assert metrics_list, "Required environment variable \"FLT_METRICS_LIST\" not found."
    metrics_list = str(metrics_list).split(",")
    _LOGGER.info("The metrics initialized were: {0}".format(metrics_list))

    # time interval at which prometheus metrics are updated for all clusters
    update_time_interval_s = int(os.getenv("FLT_UPDATE_INTERVAL_SEC", "270"))
    assert update_time_interval_s > 0, "Update interval needs to be a positive value"

    # volume where metrics are stored for consumers to consume
    metrics_save_dir = os.getenv("FLT_METRICS_SAVEDIR", "/mnt/vol")

    # scheduler to get prometheus data every update_time_interval
    scheduler = BackgroundScheduler()
    scheduler.start()
    scheduler.add_job(
        func=update_saved_prom_metrics,
        kwargs={"metrics": metrics_list, "save_dir": metrics_save_dir},
        trigger=IntervalTrigger(seconds=update_time_interval_s),
        id="update_metric_data",
        name="Ticker to collect new data from prometheus",
        replace_existing=True)
    _LOGGER.info("Started scheduler to run every {}s and save results in {}".format(update_time_interval_s, metrics_save_dir))

    # shutdown the scheduler when app closes
    atexit.register(scheduler.shutdown)


if __name__ == "__main__":
    main()
    sleep_time_interval_s = int(os.getenv("FLT_UPDATE_INTERVAL_SEC", "5"))
    while 1:
        time.sleep(sleep_time_interval_s)
