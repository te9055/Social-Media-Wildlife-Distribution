import mysql.connector

import pandas as pd
import numpy as np
import os

np.random.seed(1337)
from keras import Sequential
from keras.utils import Sequence
from keras.layers import LSTM, Dense, Masking
import numpy as np
import keras
from keras.utils import np_utils
from keras import optimizers
from keras.models import Sequential, Model
from keras.layers import Embedding, Dense, Input, concatenate, Layer, Lambda, Dropout, Activation
import datetime
from datetime import datetime
from keras.callbacks import ModelCheckpoint, EarlyStopping, Callback, TensorBoard
import tensorflow as tf
import tensorflow_hub as hub
import matplotlib.pyplot as plot
from sklearn.preprocessing import LabelEncoder
import re
from sklearn.model_selection import train_test_split

import bert
from bert import run_classifier
from bert import optimization
from bert import tokenization
import mysql.connector
from sklearn.model_selection import train_test_split

from keras import layers
from keras.callbacks import ReduceLROnPlateau

from sklearn.preprocessing import LabelEncoder
import re
from sklearn.model_selection import train_test_split
from keras import backend as K

INDEX_COLUMN = 'id'
DATA_COLUMN = 'text'
LABEL_COLUMN = 'label'
BERT_MODEL_HUB = "https://tfhub.dev/google/bert_uncased_L-12_H-768_A-12/1"
MAX_SEQ_LENGTH = 200


def dbConnection():
    mydb = mysql.connector.connect(
        host="csmysql.cs.cf.ac.uk",
        user="c1114882",
        passwd="thom9055",
        database="c1114882"
    )

    mycursor = mydb.cursor()
    mydb.autocommit = True

    return mydb, mycursor

# close database connection
def finish(mydb, mycursor):
    mycursor.close()
    mydb.close()

def getTrainData():
    train = []
    mydb, mycursor = dbConnection()
    #sql = "select id, tweet, label from wildlifeSubset_train;"
    #sql = "select id, tweet, label from trainBERTOriginal;"
    sql = "SELECT id, tweet, label from fold10 where datatype = 'train';"
    mycursor.execute(sql)
    res = mycursor.fetchall()
    finish(mydb, mycursor)
    for row in res:
        tweetId = row[0]
        text = row[1]
        label = row[2]
        train.append([tweetId,text, label])
    column_names = ['review_id', 'text', 'label']

    train_raw = pd.DataFrame(train, columns=column_names)

    return train_raw

def getTestData():
    test = []
    mydb, mycursor = dbConnection()
    #sql = "select id, tweet, actualLabel from testSetcomparison;"
    #sql = "SELECT id, tweet, label FROM testBERTOriginal;"
    sql = "SELECT id, tweet, label from fold10 where datatype = 'test';"
    mycursor.execute(sql)
    res = mycursor.fetchall()
    finish(mydb, mycursor)
    for row in res:
        tweetId = row[0]
        text = row[1]
        label = row[2]
        test.append([tweetId, text, label])
    column_names = ['review_id', 'text', 'label']
    train_raw = pd.DataFrame(test, columns=column_names)

    return train_raw


def encodeLabels(train_raw):
    LE = LabelEncoder()
    train_raw['label'] = LE.fit_transform(train_raw['label'])
    # print(train_raw.head())
    # print(len(np.unique(train_raw['label'])))

    train = train_raw.copy()
    train = train.reindex(np.random.permutation(train.index))


    return train
    # print(train.head())

def get_split(text1):
    l_total = []
    l_parcial = []
    if len(text1.split()) // 150 > 0:
        n = len(text1.split()) // 150
    else:
        n = 1
    for w in range(n):
        if w == 0:
            l_parcial = text1.split()[:200]
            l_total.append(" ".join(l_parcial))
        else:
            l_parcial = text1.split()[w * 150:w * 150 + 200]
            l_total.append(" ".join(l_parcial))
    return l_total


def splitTextAlllabels(train, val):
    # The list containing all the classes (train['SECTION'].unique())
    label_list = [x for x in np.unique(train.label)]

    train['text_split'] = train[DATA_COLUMN].apply(get_split)
    val['text_split'] = val[DATA_COLUMN].apply(get_split)


    return train, val, label_list

def bertPreprocessing(train_df, val_df):
    train_InputExamples = train_df.apply(lambda x: bert.run_classifier.InputExample(guid=None,
                                                                                    text_a=x[DATA_COLUMN],
                                                                                    text_b=None,
                                                                                    label=x[LABEL_COLUMN]), axis=1)

    # print(train_InputExamples)
    # print("Row 0 - guid of training set : ", train_InputExamples.iloc[0].guid)
    # print("\n__________\nRow 0 - text_a of training set : ", train_InputExamples.iloc[0].text_a)
    # print("\n__________\nRow 0 - text_b of training set : ", train_InputExamples.iloc[0].text_b)
    # print("\n__________\nRow 0 - label of training set : ", train_InputExamples.iloc[0].label)

    val_InputExamples = val_df.apply(lambda x: bert.run_classifier.InputExample(guid=None,
                                                                                text_a=x[DATA_COLUMN],
                                                                                text_b=None,
                                                                                label=x[LABEL_COLUMN]), axis=1)


    return train_InputExamples, val_InputExamples

def create_tokenizer_from_hub_module():
    """Get the vocab file and casing info from the Hub module."""
    with tf.Graph().as_default():
        bert_module = hub.Module(BERT_MODEL_HUB)
        tokenization_info = bert_module(signature="tokenization_info", as_dict=True)
        with tf.Session() as sess:
            vocab_file, do_lower_case = sess.run([tokenization_info["vocab_file"],
                                                  tokenization_info["do_lower_case"]])

    return bert.tokenization.FullTokenizer(vocab_file=vocab_file, do_lower_case=do_lower_case)


# Convert our train and validation features to InputFeatures that BERT understands.
def convFeatures(train_InputExamples, label_list, MAX_SEQ_LENGTH, tokenizer, val_InputExamples):
    train_features = bert.run_classifier.convert_examples_to_features(train_InputExamples, label_list, MAX_SEQ_LENGTH,
                                                                      tokenizer)
    val_features = bert.run_classifier.convert_examples_to_features(val_InputExamples, label_list, MAX_SEQ_LENGTH,
                                                                    tokenizer)


    return train_features, val_features


def create_model(is_predicting, input_ids, input_mask, segment_ids, labels, num_labels):
    bert_module = hub.Module(BERT_MODEL_HUB, trainable=True)
    bert_inputs = dict(input_ids=input_ids, input_mask=input_mask, segment_ids=segment_ids)
    bert_outputs = bert_module(inputs=bert_inputs, signature="tokens", as_dict=True)

    # Use "pooled_output" for classification tasks on an entire sentence.
    # Use "sequence_outputs" for token-level output.
    output_layer = bert_outputs["pooled_output"]
    # with tf.Session() as sess:
    output_layer1 = bert_outputs["pooled_output"]
    # output_layer1 = 999
    hidden_size = output_layer.shape[-1].value

    # Create our own layer to tune for politeness data.
    output_weights = tf.get_variable("output_weights", [num_labels, hidden_size],
                                     initializer=tf.truncated_normal_initializer(stddev=0.02))

    output_bias = tf.get_variable("output_bias", [num_labels], initializer=tf.zeros_initializer())

    with tf.variable_scope("loss"):
        # Dropout helps prevent overfitting
        output_layer = tf.nn.dropout(output_layer, keep_prob=0.8)

        logits = tf.matmul(output_layer, output_weights, transpose_b=True)
        logits = tf.nn.bias_add(logits, output_bias)
        log_probs = tf.nn.log_softmax(logits, axis=-1)

        # Convert labels into one-hot encoding
        one_hot_labels = tf.one_hot(labels, depth=num_labels, dtype=tf.float32)

        predicted_labels = tf.squeeze(tf.argmax(log_probs, axis=-1, output_type=tf.int32))
        # If we're predicting, we want predicted labels and the probabiltiies.
        if is_predicting:
            return (predicted_labels, log_probs, output_layer1)

        # If we're train/eval, compute loss between predicted and actual label
        per_example_loss = -tf.reduce_sum(one_hot_labels * log_probs, axis=-1)
        loss = tf.reduce_mean(per_example_loss)
        return (loss, predicted_labels, log_probs)


def model_fn_builder(num_labels, learning_rate, num_train_steps, num_warmup_steps):
    """Returns `model_fn` closure for TPUEstimator."""

    def model_fn(features, labels, mode, params):  # pylint: disable=unused-argument
        """The `model_fn` for TPUEstimator."""

        input_ids = features["input_ids"]
        input_mask = features["input_mask"]
        segment_ids = features["segment_ids"]
        label_ids = features["label_ids"]

        is_predicting = (mode == tf.estimator.ModeKeys.PREDICT)

        # TRAIN and EVAL
        if not is_predicting:

            (loss, predicted_labels, log_probs) = create_model(
                is_predicting, input_ids, input_mask, segment_ids, label_ids, num_labels)

            train_op = bert.optimization.create_optimizer(
                loss, learning_rate, num_train_steps, num_warmup_steps, use_tpu=False)

            # Calculate evaluation metrics.
            def metric_fn(label_ids, predicted_labels):
                accuracy = tf.metrics.accuracy(label_ids, predicted_labels)
                true_pos = tf.metrics.true_positives(
                    label_ids,
                    predicted_labels)
                true_neg = tf.metrics.true_negatives(
                    label_ids,
                    predicted_labels)
                false_pos = tf.metrics.false_positives(
                    label_ids,
                    predicted_labels)
                false_neg = tf.metrics.false_negatives(
                    label_ids,
                    predicted_labels)

                return {
                    "eval_accuracy": accuracy,
                    "true_positives": true_pos,
                    "true_negatives": true_neg,
                    "false_positives": false_pos,
                    "false_negatives": false_neg,
                }

            eval_metrics = metric_fn(label_ids, predicted_labels)

            if mode == tf.estimator.ModeKeys.TRAIN:
                return tf.estimator.EstimatorSpec(mode=mode,
                                                  loss=loss,
                                                  train_op=train_op)
            else:
                return tf.estimator.EstimatorSpec(mode=mode,
                                                  loss=loss,
                                                  eval_metric_ops=eval_metrics)
        else:
            (predicted_labels, log_probs, output_layer) = create_model(
                is_predicting, input_ids, input_mask, segment_ids, label_ids, num_labels)
            predictions = {
                'probabilities': log_probs,
                'labels': predicted_labels,
                'pooled_output': output_layer
            }
            return tf.estimator.EstimatorSpec(mode, predictions=predictions)

    # Return the actual model function in the closure
    return model_fn

def splitData(valOld):
    test, val = train_test_split(valOld, test_size=0.5, random_state=35)
    test.reset_index(drop=True, inplace=True)
    val.reset_index(drop=True, inplace=True)
    return test, val

def main():
    train_raw = getTrainData()
    test_raw = getTestData()

    train = encodeLabels(train_raw)
    val = encodeLabels(test_raw)
    #test, val = splitData(valOld)


    train, val, label_list = splitTextAlllabels(train, val)
    print(train.head())
    print(val.head())
    print(label_list)

    train_l = []
    label_l = []
    index_l = []
    train_id_l = []
    for idx, row in train.iterrows():
        for l in row['text_split']:
            train_l.append(l)
            label_l.append(row['label'])
            index_l.append(idx)
            train_id_l.append(row['review_id'])
    len(train_l), len(label_l), len(index_l)
    train_df = pd.DataFrame({INDEX_COLUMN: train_id_l, DATA_COLUMN: train_l, LABEL_COLUMN: label_l})

    val_l = []
    val_label_l = []
    val_index_l = []
    val_id_l = []
    for idx, row in val.iterrows():
        for l in row['text_split']:
            val_l.append(l)
            val_label_l.append(row['label'])
            val_index_l.append(idx)
            val_id_l.append(row['review_id'])
    len(val_l), len(val_label_l), len(val_index_l)
    val_df = pd.DataFrame({INDEX_COLUMN: val_id_l, DATA_COLUMN: val_l, LABEL_COLUMN: val_label_l})


    # val_df = finalPrepVal(val)
    print(train_df.shape)
    print(val_df.shape)
    train_InputExamples, val_InputExamples = bertPreprocessing(train_df, val_df)
    tokenizer = create_tokenizer_from_hub_module()
    print(len(tokenizer.vocab.keys()))
    # Here is what the tokenised sample of the first training set observation looks like
    print(tokenizer.tokenize(train_InputExamples.iloc[0].text_a))
    # Example on first observation in the training set

    train_features, val_features = convFeatures(train_InputExamples, label_list, 200, tokenizer, val_InputExamples)
    print(train_features)
    print("--------------------------")
    print(val_features)

    BATCH_SIZE = 16
    LEARNING_RATE = 2e-5
    #LEARNING_RATE = 3e-5
    NUM_TRAIN_EPOCHS = 4.0
    # Warmup is a period of time where the learning rate is small and gradually increases--usually helps training.
    WARMUP_PROPORTION = 0.1
    # Model configs
    SAVE_CHECKPOINTS_STEPS = 300
    SAVE_SUMMARY_STEPS = 100

    # Compute train and warmup steps from batch size
    num_train_steps = int(len(train_features) / BATCH_SIZE * NUM_TRAIN_EPOCHS)
    num_warmup_steps = int(num_train_steps * WARMUP_PROPORTION)

    # Specify output directory and number of checkpoint steps to save
    run_config = tf.estimator.RunConfig(
        model_dir='bert_news_category',
        save_summary_steps=SAVE_SUMMARY_STEPS,
        save_checkpoints_steps=SAVE_CHECKPOINTS_STEPS)

    model_fn = model_fn_builder(
        num_labels=len(label_list),
        learning_rate=LEARNING_RATE,
        num_train_steps=num_train_steps,
        num_warmup_steps=num_warmup_steps)

    estimator = tf.estimator.Estimator(
        model_fn=model_fn,
        config=run_config,
        params={"batch_size": BATCH_SIZE})

    # Create an input function for training. drop_remainder = True for using TPUs.
    train_input_fn = bert.run_classifier.input_fn_builder(
        features=train_features,
        seq_length=MAX_SEQ_LENGTH,
        is_training=True,
        drop_remainder=False)

    # Create an input function for validating. drop_remainder = True for using TPUs.
    val_input_fn = run_classifier.input_fn_builder(
        features=val_features,
        seq_length=MAX_SEQ_LENGTH,
        is_training=False,
        drop_remainder=False)

    # Training the model
    print(f'Beginning Training!')
    current_time = datetime.now()
    estimator.train(input_fn=train_input_fn, max_steps=num_train_steps)
    print("Training took time ", datetime.now() - current_time)

    # Evaluating the model with Validation set
    print(estimator.evaluate(input_fn=val_input_fn, steps=None))

    '''

    # safevals = []
    # A method to get predictions
    def getPrediction(in_sentences, type_output="features"):
        # def getPrediction(in_sentences, type_output=""):
        # A list to map the actual labels to the predictions
        labels = np.unique(train['label'])
        input_examples = [run_classifier.InputExample(guid="", text_a=x, text_b=None, label=0) for x in in_sentences]
        input_features = run_classifier.convert_examples_to_features(input_examples, label_list, MAX_SEQ_LENGTH,
                                                                     tokenizer)
        # Predicting the classes
        predict_input_fn = run_classifier.input_fn_builder(features=input_features, seq_length=MAX_SEQ_LENGTH,
                                                           is_training=False, drop_remainder=False)
        predictions = estimator.predict(predict_input_fn)

        if type_output == "features":
            return [prediction['pooled_output'] for _, prediction in enumerate(predictions)]
        else:
            # print("HELLo")
            # print("in_sentences, predictions")
            # for sentence, prediction in zip(in_sentences, predictions):
            #    print("s: ",sentence)
            #    print("prediction['probabilities']:",prediction['probabilities'])
            #    print("prediction['labels']:",prediction['labels'])
            #    print("labels[prediction['labels']: ",labels[prediction['labels']])
            #    safevals.append([sentence,prediction['probabilities'],labels[prediction['labels']]])

            return ([(sentence, prediction['probabilities'], prediction['labels'],
                      prediction['labels'], labels[prediction['labels']]) for sentence, prediction in
                     zip(in_sentences, predictions)])

    # train_df.to_csv('exportTrain_originalsubset.csv', index=False, header=True)
    # val_df.to_csv('exportVal_originalsubset.csv', index=False, header=True)
    tr_emb = np.apply_along_axis(getPrediction, 0, np.array(train_df[DATA_COLUMN]))
    val_emb = np.apply_along_axis(getPrediction, 0, np.array(val_df[DATA_COLUMN]))
    #print(val_emb.shape, tr_emb.shape)
    # print(val_emb)
    # fObj = pd.DataFrame(safevals)
    # fObj.to_csv('bertProbs.csv', index=False, header=True)

    aux = -1
    len_l = 0
    train_x = {}
    for l, emb in zip(index_l, tr_emb):
        if l in train_x.keys():
            train_x[l] = np.vstack([train_x[l], emb])
        else:
            train_x[l] = [emb]

    len(train_x.keys())

    train_l_final = []
    label_l_final = []
    trainids = []
    for k in train_x.keys():
        trainids.append(k)
        train_l_final.append(train_x[k])
        label_l_final.append(train.loc[k]['label'])

    df_train = pd.DataFrame({'id': trainids, 'emb': train_l_final, 'label': label_l_final, })
    print(df_train.head())
    df_train.to_csv('trainBERT_embeddingsnewst.csv', index=False, header=True)

    aux = -1
    len_l = 0
    val_x = {}

    for l, emb in zip(val_index_l, val_emb):
        if l in val_x.keys():
            val_x[l] = np.vstack([val_x[l], emb])
        else:
            val_x[l] = [emb]

    val_l_final = []
    vlabel_l_final = []
    valids = []
    for k in val_x.keys():
        valids.append(k)
        val_l_final.append(val_x[k])
        vlabel_l_final.append(val.loc[k]['label'])

    df_val = pd.DataFrame({'id': valids, 'emb': val_l_final, 'label': vlabel_l_final})
    print(df_val.head())
    df_val.to_csv('devBERT_embeddingsnewst.csv', index=False, header=True)
    df_both = df_val
    df_val, df_test = train_test_split(df_val, test_size=0.4, random_state=35)
    df_test.to_csv('testBERT_embeddingsnewst.csv', index=False, header=True)
    '''

main()