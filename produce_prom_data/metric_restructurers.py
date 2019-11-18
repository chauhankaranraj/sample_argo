import time
import pandas as pd


# NOTE: this function is taken directly from insights-ocp library
# developed here: https://gitlab.cee.redhat.com/ccx/insights-ocp
def metric_to_dataframe(self, metric):
    """Convert mertic data to pandas DataFrame.

    Args:
        metric (list): List of dictionaries coming from raw telemetry
            requests (produced by :py:func:`__raw_metric_latest` or
            :py:func:`__raw_metric_at_time`)

    Returns
        pd.Dataframe: With columns from the metric. The 'value' column
            contains value of the last time point.
    """
    # in case there are multiple time-value pairs withing the 'value' key,
    # get the last one
    def last_time_value(i):
        return i["values"][-1] if "values" in i else i["value"]

    return pd.DataFrame([{**i["metric"], "value": last_time_value(i)[1]} for i in metric])


def opconds_metrics_to_df(metrics_raw):
    """Converts `cluster_operator_conditions` Prometheus
    metric into a dataframe

    Arguments:
        metrics_raw {dict} -- raw json returned from Prometheus

    Returns:
        pd.DataFrame -- [description]
    """
    # convert to dataframe and fix dtype inference
    df = metric_to_dataframe(metrics_raw)
    df['value'] = df['value'].astype(np.float64)

    # clayton suggested filling data with empty string
    # however doing that will make it difficult to do some pandas column name operations
    # so fill it with the string "empty"
    df['reason'] = df['reason'].fillna("empty")

    # convert to one-hot encoding
    opcond_keep_cols = ['_id', 'name', 'condition', 'value', 'reason']
    df = df[opcond_keep_cols].groupby(['_id', 'name', 'condition', 'reason']).first()

    # make each condition for each operator a column in the data
    df = df.unstack(level=[lvl_idx for lvl_idx in range(1, df.index.nlevels)])

    # checking skipped to reduce memory footprint
    # # ensure no deployment_ids were lost in translation (literally, "translation" of the matrix)
    # assert df.index.nunique()==df['_id'].nunique()

    # fill nans
    df = df.fillna(0)

    # convert multi-dimensional column indexing into single dimnsion
    new_colnames = ['_'.join((op, cond, reason))
                    for op,cond,reason in zip(df.columns.get_level_values(1),
                                                df.columns.get_level_values(2),
                                                df.columns.get_level_values(3))]
    df.columns = new_colnames

    return df


def installer_metrics_to_df(metrics_raw):
    # this seems to be how labels are assigned, according to the query on grafana
    # label_replace(label_replace(cluster_installer{_id="$_id"}, "type", "UPI", "type", ""), "type", "IPI", "type", "openshift-install")
    df = metric_to_dataframe(metrics_raw)
    df['type'] = df['type'].replace(to_replace=[np.nan, 'openshift-install'], value=['UPI', 'IPI'])

    # ensure that ids are unique. then make id the index into df
    df = df.drop_duplicates(subset=['_id', 'version', 'type'])
    assert df['_id'].nunique()==len(df)
    df = df.set_index(keys='_id')

    # keep only relevant columns
    return pd.get_dummies(df[['type']], prefix='install_type')


def version_metrics_to_df(metrics_raw, duration_end_ts=None):
    def get_version(fullstr):
        """
        Extract major version number from verbose string
        e.g. "4.1.18" from openshift-v4.1.18
        or "4.2.0" from 4.2.0-0.nightly-2019-09-25-233506

        NOTE: if it wasnt for the edge case of "openshift-v4.1.18", a simple transform
        using `.apply(lambda x: x.split('-')[0])` would have sufficed
        """
        for part in str(fullstr).split('-'):
            if part.count('.')==2:
                return ''.join([i for i in part if i.isnumeric() or i=='.'])
        return np.nan

    # id not provided, use current time
    if duration_end_ts is None:
        duration_end_ts = time.time()

    # convert to dataframe and
    df = metric_to_dataframe(metrics_raw)
    # drop where version does not exist
    df = df[~df['version'].isna()]
    # fix dtype inference
    df['value'] = df['value'].astype(np.float64)

    # ensure that ids are unique. then make id the index into df
    df = df.groupby('_id').apply(lambda g: g[g['value']==g['value'].max()].drop_duplicates(keep='last')).reset_index(level=1, drop=True)

    # keep major version only. remove trailing info in ci/nightly builds
    df['version'] = df['version'].apply(get_version)

    # add duration, i.e. how long has a cluster been in that version_type for
    df['version_duration'] = current_timestamp - versions_df['value']

    # one hot encode types and versions. keep only relevant columns
    df = df.merge(pd.get_dummies(df['type'], prefix='version'), how='left', left_index=True, right_index=True)
    df = df.merge(pd.get_dummies(df['version'], prefix='version'), how='left', left_index=True, right_index=True)
    return df[[col for col in df.columns if 'version_' in col]]
