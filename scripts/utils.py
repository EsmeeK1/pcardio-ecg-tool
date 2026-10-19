def aggregate_diagnostic(y_dic, agg_df):
    """
    Aggregate diagnostic labels into superclasses.

    Parameters:
    y_dic (dict): Dictionary of scp_codes.
    agg_df (DataFrame): DataFrame containing diagnostic information.

    Returns:
    list: Unique diagnostic superclasses.
    """
    tmp = []
    for key in y_dic.keys():
        if key in agg_df.index:
            tmp.append(agg_df.loc[key].diagnostic_class)
    return list(set(tmp))