import shutil
import numpy as np
import pandas as pd
import tensorflow as tf
import urllib.parse as urlparse

from helpers_proc import primaryDomain, extFind, process_date
print(tf.__version__)


train_df = pd.read_csv('./train.csv', sep=',')
eval_df = pd.read_csv('./eval.csv', sep=',')
test_df = pd.read_csv('./test.csv', sep=',')

def add_more_features(dataframe):
    df = dataframe.copy()
    
    df['domain_temp'] = ""
    df['domain_temp'] = df.url.apply(lambda row: extFind(row,True))
    df['url_length'] = df.url.apply(lambda row: len(row))
    df['query_string'] = df.url.apply(lambda row: urlparse.urlparse(row).query if urlparse.urlparse(row).query != '' else 'None')
    df['query_length'] = df.query_string.apply(lambda row: len(row))
    df['primary'] = df.domain_temp.apply(lambda row: row[1] if row[0] in ['www','ww1','ww2'] else row[0])
    df['primary_Length'] = df.primary.apply(lambda row: len(row))
    df['num_periods'] = df.url.apply(lambda row: row.count("."))
    df['num_exclam'] = df.url.apply(lambda row: row.count("!"))
    df['num_quest'] = df.url.apply(lambda row: row.count("?"))
    df['num_perc'] = df.url.apply(lambda row: row.count("%"))
    df['num_numbers'] = df.url.apply(lambda row: sum(c.isdigit() for c in row))
    df['last_year_modified'] = process_date(df)
    df = df.drop(["query_string","primary","domain_temp"], axis=1)
    return df 

train_df = add_more_features(train_df)
eval_df = add_more_features(eval_df)
test_df = add_more_features(test_df)


def get_vocabulary_list(category):
    train_cat = list(train_df[category].unique())
    eval_cat = list(eval_df[category].unique())
    test_cat = list(test_df[category].unique())
    return sorted(set(train_cat + eval_cat + test_cat))


# Create pandas input function
def make_train_input_fn(df, batch_size, num_epochs):
    return tf.estimator.inputs.pandas_input_fn(
        x = df,
        y = df['isHiddenFraudulent'],
        batch_size = batch_size,
        num_epochs = num_epochs,
        shuffle = True,
        queue_capacity = 1024,
        num_threads = 1
    )

def make_eval_input_fn(df, batch_size):
    return tf.estimator.inputs.pandas_input_fn(
        x = df,
        y = df['isHiddenFraudulent'], 
        batch_size = 256,
        num_epochs = 1,
        shuffle = False,
        queue_capacity = 1024,
        num_threads = 1
    )

def make_test_input_fn(df):
    return tf.estimator.inputs.pandas_input_fn(
        x = df,
        batch_size = 16,
        num_epochs = 1,
        shuffle = False,
        queue_capacity = 1024,
        num_threads = 1
    )


num_int_features = ['url_length', 'contentLength', 'query_length']
category_features = ['serverType', 'poweredBy', 'contentType', 'last_year_modified']

def create_feature_cols(embedding=False):
    
    tf_fc_emb = tf.feature_column.embedding_column
    tf_fc_num = tf.feature_column.numeric_column
    tf_fc_cat = tf.feature_column.categorical_column_with_vocabulary_list
    
    num_cols = [tf_fc_num(col) for col in num_int_features]
    cat_cols = [tf_fc_cat(key=col, 
                          vocabulary_list=get_vocabulary_list(col)) for col in category_features]
    if embedding:
        cat_cols = [tf_fc_emb(col, 16) for col in cat_cols]
    
    cols = num_cols + cat_cols
    
    #try bucketize url_length 5 
    return cols 

feature_cols = create_feature_cols(embedding=True)


def serving_input_fn():
    
    n_int = len(num_int_features)
    n_cat = len(category_features)
    
    num_placeholders = [tf.placeholder(tf.int64, [None]) for i in range(n_int)]
    string_placeholders = [tf.placeholder(tf.string, [None]) for i in range(n_cat)]
    
    feat_names = num_int_features + category_features
    placeholders = num_placeholders + string_placeholders
    
    json_feature_placeholders = dict(zip(feat_names, placeholders))
    
    features = json_feature_placeholders
    
    return tf.estimator.export.ServingInputReceiver(features, json_feature_placeholders)


# Create estimator train and evaluate function


def train_and_evaluate(output_dir, model='linear'):
    
    run_config = tf.estimator.RunConfig(model_dir=output_dir, 
                                        save_summary_steps=50,
                                        keep_checkpoint_max=10,
                                        save_checkpoints_steps=SAVE_CKPT_STEPS)
    
    if model == 'linear':
        estimator = tf.estimator.LinearClassifier(feature_columns=feature_cols, 
                                               config=run_config)
    else:
        estimator = tf.estimator.DNNClassifier(feature_columns=feature_cols, hidden_units=HIDDEN_UNITS,
                                           config=run_config)

    train_spec = tf.estimator.TrainSpec(input_fn=make_train_input_fn(train_df, BATCH_SIZE, NUM_EPOCH), 
                                        max_steps=MAX_STEPS)

    export_latest = tf.estimator.LatestExporter(name='exporter', 
                                                serving_input_receiver_fn=serving_input_fn,
                                                exports_to_keep=None)

    eval_spec = tf.estimator.EvalSpec(input_fn=make_eval_input_fn(eval_df, BATCH_SIZE), 
                                    steps=None,
                                    start_delay_secs = 1, # start evaluating after N seconds
                                    throttle_secs = EVAL_INTERVAL_SEC,     # evaluate every N seconds
                                    exporters=export_latest
                                    )

    tf.estimator.train_and_evaluate(estimator, train_spec, eval_spec)
    
    return estimator 