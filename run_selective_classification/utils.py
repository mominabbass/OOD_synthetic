import numpy as np
import time
from copy import deepcopy
import os
import sys
import torch
import pickle
import openai
import random
from transformers import GPT2Tokenizer, GPT2LMHeadModel, GPTJForCausalLM, LlamaForCausalLM, LlamaTokenizer, BitsAndBytesConfig, AutoConfig, AutoModelForCausalLM, T5Tokenizer, T5ForConditionalGeneration, TFT5EncoderModel
from accelerate import init_empty_weights, load_checkpoint_and_dispatch
from torch.autograd import Variable

#prompt tuning libraries
from transformers import AutoModelForCausalLM, AutoTokenizer, default_data_collator, get_linear_schedule_with_warmup, Trainer
from peft import get_peft_config, get_peft_model, PromptTuningInit, PromptTuningConfig, TaskType, PeftType, LoraConfig, TaskType, PeftConfig, PeftModel
from datasets import load_dataset
from torch.utils.data import DataLoader
from tqdm import tqdm
from transformers.optimization import Adafactor, AdafactorSchedule
import pandas as pd
from huggingface_hub import notebook_login

tokenizer = GPT2Tokenizer.from_pretrained('gpt2')

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# ROOT_DIR = os.path.dirname(os.path.realpath(__file__))
SAVE_DIR = os.path.join(ROOT_DIR, 'saved_results')
if not os.path.isdir(SAVE_DIR):
    os.mkdir(SAVE_DIR)
    print(f"mkdir at {SAVE_DIR} for saving results")


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def chunk_size_helper(params):
    # Set the batch size (the size of the chunks determines the batch size). Default to 4 for GPT-2 and 20 for OpenAI if
    # no batch size is specified.
    bs = params['bs']
    if bs is None:
        if 'gpt2' in params['model']:
            return 1
        elif 'gptj' in params['model']:
            return 1
        elif 'llama2_7b' in params['model']:
            return 1
        elif 't5' in params['model']:
            return 1
        else:
            assert params['model'] in ['ada', 'babbage', 'curie', 'davinci', 'ada-beta', 'babbage-beta', 'curie-beta',
                                       'davinci-beta']
            return 20
    else:
        return bs

def random_sampling(sentences, labels, num, max_length=None):
    """randomly sample subset of the training pairs"""
    if max_length is not None:
        filtered_sentences = []
        filtered_labels = []
        for index in range(len(sentences)):
            if len(sentences[index]) <= max_length:
                filtered_sentences.append(sentences[index])
                filtered_labels.append(labels[index])
        sentences = filtered_sentences
        labels = filtered_labels

    assert len(sentences) == len(labels)
    if num > len(labels):
        assert False, f"you tried to randomly sample {num}, which is more than the total size of the pool {len(labels)}"

    idxs = np.random.choice(len(labels), size=num, replace=False)
    selected_sentences = [sentences[i] for i in idxs]
    selected_labels = [labels[i] for i in idxs]
    return deepcopy(selected_sentences), deepcopy(selected_labels)


gpt2_model = None
gpt2_tokenizer = None
def setup_gpt2(model_name, params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels):
    # load the GPT-J model
    global gpt2_model
    global gpt2_tokenizer
    if gpt2_model is None:
        print("Setting up GPT-2 model")
        gpt2_tokenizer = GPT2Tokenizer.from_pretrained(model_name)
        gpt2_model = GPT2LMHeadModel.from_pretrained(model_name, pad_token_id=gpt2_tokenizer.eos_token_id)
        gpt2_model.eval().cuda()

        # to batch generation, we pad on the left and mask those positions out.
        gpt2_tokenizer.padding_side = "left"
        gpt2_tokenizer.pad_token = gpt2_tokenizer.eos_token
        gpt2_model.config.pad_token_id = gpt2_model.config.eos_token_id
        print("Finished")

       
gptj_model = None
gptj_tokenizer = None
def setup_gptj(model_name, params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels):
    # load the GPT-J model
    global gptj_model
    global gptj_tokenizer
    if gptj_model is None:
        print("Setting up GPT-J model")
        gptj_tokenizer = GPT2Tokenizer.from_pretrained("EleutherAI/gpt-j-6B")
        gptj_model = GPTJForCausalLM.from_pretrained("EleutherAI/gpt-j-6B", revision="float16",
                                                     torch_dtype=torch.float16, low_cpu_mem_usage=True, pad_token_id=gptj_tokenizer.eos_token_id)
        gptj_model.eval().cuda()
        
        # to batch generation, we pad on the left and mask those positions out.
        gptj_tokenizer.padding_side = "left"
        gptj_tokenizer.pad_token = gptj_tokenizer.eos_token
        gptj_model.config.pad_token_id = gptj_model.config.eos_token_id
        print("Finished")

llamma2_7b_model = None
llamma2_7b_tokenizer  = None
def setup_llama2_7b(model_name, params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels):
    # load the Llama-2 7b model
    global llamma2_7b_model
    global llamma2_7b_tokenizer
    if llamma2_7b_model is None:
        print("Setting up Llama-2 7B model")

        if params['dataset'] == 'civil_comments_toxicity_OOD_sst2':
            folder_name = "saved_checkpoints/selective_classification_binary-pos-neg_sst2_Llama-2-7b-hf_acc0.924.pt"
        elif params['dataset'] == 'response_beavertails_unethical_OOD_discrimincation-hate':
            folder_name = "saved_checkpoints/selective_classification_binary-pos-neg_hate_discrim_Llama-2-7b-hf_acc0.862.pt"
        else:
            folder_name = "saved_checkpoints/selective_classification_binary-pos-neg_sexual_drug_Llama-2-7b-hf_acc0.823.pt"
        
        model_name = '/home/local_acc/hugginface/hub/Llama-2-7b-hf'

        ## Use device_map to distribute model layers across available devices if your GPUs have limited capacity.
        # device_map = {'model.embed_tokens': 0, 'model.layers.0': 0, 'model.layers.1': 0, 'model.layers.2': 0,
        #               'model.layers.3': 0, 'model.layers.4': 0, 'model.layers.5': 0, 'model.layers.6': 0,
        #               'model.layers.7': 0,
        #               'model.layers.8': 0, 'model.layers.9': 0, 'model.layers.10': 0, 'model.layers.11': 0,
        #               'model.layers.12': 0,
        #               'model.layers.13': 0, 'model.layers.14': 0, 'model.layers.15': 0, 'model.layers.16': 0,
        #               'model.layers.17': 0,
        #               'model.layers.18': 1, 'model.layers.19': 1, 'model.layers.20': 1, 'model.layers.21': 1,
        #               'model.layers.22': 1,
        #               'model.layers.23': 1, 'model.layers.24': 1, 'model.layers.25': 1, 'model.layers.26': 1,
        #               'model.layers.27': 1,
        #               'model.layers.28': 1, 'model.layers.29': 1, 'model.layers.30': 1, 'model.layers.31': 1,
        #               'model.layers.32': 1,
        #               'model.layers.33': 1, 'model.layers.34': 1, 'model.layers.35': 1, 'model.layers.36': 1,
        #               'model.layers.37': 1,
        #               'model.layers.38': 2, 'model.layers.39': 2, 'model.norm': 2, 'lm_head': 2}

        config = AutoConfig.from_pretrained(model_name)
        config.pretraining_tp = 1
        llamma2_7b_model = LlamaForCausalLM.from_pretrained(model_name, device_map='sequential', config=config,
                                                             torch_dtype=torch.float16,
                                                             low_cpu_mem_usage=True)  # set device_map manually or use ("auto", "balanced", "balanced_low_0", "sequential") see https://huggingface.co/docs/accelerate/usage_guides/big_modeling

        llamma2_7b_model = PeftModel.from_pretrained(llamma2_7b_model, folder_name)
        llamma2_7b_tokenizer = AutoTokenizer.from_pretrained(model_name)
        # to batch generation, we pad on the left and mask those positions out.
        llamma2_7b_tokenizer.padding_side = "left"
        llamma2_7b_tokenizer.pad_token = llamma2_7b_tokenizer.eos_token
        llamma2_7b_model.config.pad_token_id = llamma2_7b_model.config.eos_token_id
        print("Finished")

def complete_gptj(prompt, label_dict, l=1, normalize=True):
    if isinstance(prompt, str):
        prompt = [prompt]  # the code below assumes a list
    input_ids = gptj_tokenizer.batch_encode_plus(prompt, return_tensors="pt", padding=True)
    # greedily generate l tokens
    assert l == 1
    if(len(input_ids['input_ids']) > 1023):
        input_ids['input_ids'] = input_ids['input_ids'][0:1023]
        input_ids['attention_mask'] = input_ids['attention_mask'][0:1023]
    total_sequences = gptj_model.generate(input_ids=input_ids['input_ids'].cuda(),
                                          attention_mask=input_ids['attention_mask'].cuda(),
                                          max_length=l + len(input_ids['input_ids'][0]), do_sample=False)

    # we are left padding, so we need to adjust the position IDs
    attention_mask = (total_sequences != 50256).float()
    position_ids = attention_mask.long().cumsum(-1) - 1
    position_ids.masked_fill_(attention_mask == 0, 1)
    # get the logits for the context and the next l tokens
    logits = gptj_model.forward(input_ids=total_sequences, attention_mask=attention_mask, position_ids=position_ids,
                                return_dict=True).logits.detach().cpu()
    # get the top tokens and probs for the generated l tokens
    prediction_probs = torch.softmax(logits[:, -l - 1], dim=1).cpu().numpy()
    prediction_logits = logits[:, -l - 1].cpu().numpy()
    # bs x 50257
    num_classes = len(label_dict)

    all_test_prediction_logits = []
    all_test_prediction_probs = []
    for ind in range(prediction_logits.shape[0]):
        label_probs = [0] * num_classes
        label_logits = [0] * num_classes
        for label_id, label_list in label_dict.items():
            # assert len(label_list)==1
            label = label_list[0]
            label = " " + label
            token = gptj_tokenizer.encode(label)[0]
            label_probs[label_id] = prediction_probs[ind][token]
            label_logits[label_id] = prediction_logits[ind][token]

        if normalize:
            label_probs = [prob / np.sum(label_probs) for prob in label_probs]
        all_test_prediction_probs.append(label_probs)
        all_test_prediction_logits.append(label_logits)

    return all_test_prediction_logits, all_test_prediction_probs


def complete_llamma2_7b(prompt, label_dict, l=1, normalize=True):
    if isinstance(prompt, str):
        prompt = [prompt]  # the code below assumes a list
    input_ids = llamma2_7b_tokenizer.batch_encode_plus(prompt, return_tensors="pt", padding=True)
    # greedily generate l tokens
    assert l == 1
    total_sequences = llamma2_7b_model.generate(input_ids=input_ids['input_ids'].cuda(),
                                          attention_mask=input_ids['attention_mask'].cuda(),
                                          max_length=l + len(input_ids['input_ids'][0]), do_sample=False)
    # we are left padding, so we need to adjust the position IDs
    attention_mask = (total_sequences != 31999).float()
    position_ids = attention_mask.long().cumsum(-1) - 1
    position_ids.masked_fill_(attention_mask == 0, 1)
    # get the logits for the context and the next l tokens
    logits = llamma2_7b_model.forward(input_ids=total_sequences, attention_mask=attention_mask, position_ids=position_ids,
                                return_dict=True).logits.detach().cpu()
    # get the top tokens and probs for the generated l tokens
    prediction_probs = torch.softmax(logits[:, -l - 1].float(), dim=1).cpu().numpy()
    prediction_logits = logits[:, -l - 1].cpu().numpy()

    # bs x 31999
    num_classes = len(label_dict)
    all_test_prediction_logits = []
    all_test_prediction_probs = []
    for ind in range(prediction_logits.shape[0]):
        label_probs = [0] * num_classes
        label_logits = [0] * num_classes
        for label_id, label_list in label_dict.items():
            # assert len(label_list)==1
            label = label_list[0]
            label = " " + label
            token = llamma2_7b_tokenizer.encode(label)[2]
            # print("token", token)
            label_probs[label_id] = prediction_probs[ind][token]
            label_logits[label_id] = prediction_logits[ind][token]

        if normalize:
            label_probs = [prob / np.sum(label_probs) for prob in label_probs]
        all_test_prediction_probs.append(label_probs)
        all_test_prediction_logits.append(label_logits)

    return all_test_prediction_logits, all_test_prediction_probs


def complete_gpt2(prompt, label_dict, l=1, normalize=True):
    if isinstance(prompt, str):
        prompt = [prompt]  # the code below assumes a list
    input_ids = gpt2_tokenizer.batch_encode_plus(prompt, return_tensors="pt", padding=True)
    # greedily generate l tokens
    assert l == 1
    if (len(input_ids['input_ids'][0]) > 1024):
        input_ids['input_ids'] = input_ids['input_ids'][:, :1023]
        input_ids['attention_mask'] = input_ids['attention_mask'][:, :1023]
    total_sequences = gpt2_model.generate(input_ids=input_ids['input_ids'].cuda(),
                                          attention_mask=input_ids['attention_mask'].cuda(),
                                          max_length=l + len(input_ids['input_ids'][0]), do_sample=False)

    # we are left padding, so we need to adjust the position IDs
    attention_mask = (total_sequences != 50256).float()
    position_ids = attention_mask.long().cumsum(-1) - 1
    position_ids.masked_fill_(attention_mask == 0, 1)
    # get the logits for the context and the next l tokens

    if (total_sequences.size(1) > 1024):
        total_sequences = total_sequences[:, :1023]
        attention_mask = attention_mask[:, :1023]
        position_ids = position_ids[:, :1023]
    logits = gpt2_model.forward(input_ids=total_sequences, attention_mask=attention_mask, position_ids=position_ids,
                                return_dict=True).logits.detach().cpu()
    # get the top tokens and probs for the generated l tokens
    prediction_probs = torch.softmax(logits[:, -l - 1], dim=1).cpu().numpy()
    prediction_logits = logits[:, -l - 1].cpu().numpy()
    # bs x 50257
    num_classes = len(label_dict)

    all_test_prediction_logits = []
    all_test_prediction_probs = []
    for ind in range(prediction_logits.shape[0]):
        label_probs = [0] * num_classes
        label_logits = [0] * num_classes
        for label_id, label_list in label_dict.items():
            # assert len(label_list)==1
            label = label_list[0]
            label = " " + label
            token = gpt2_tokenizer.encode(label)[0]
            label_probs[label_id] = prediction_probs[ind][token]
            label_logits[label_id] = prediction_logits[ind][token]

        if normalize:
            label_probs = [prob / np.sum(label_probs) for prob in label_probs]
        all_test_prediction_probs.append(label_probs)
        all_test_prediction_logits.append(label_logits)

    return all_test_prediction_logits, all_test_prediction_probs


def construct_prompt(params, train_sentences, train_labels, test_sentence):
    """construct a single prompt to be fed into the model"""
    # special case when the user defines a custom prompt function.
    if ('prompt_func' in params.keys()) and (params['prompt_func'] is not None):
        return params['prompt_func'](params, train_sentences, train_labels, test_sentence)

    # take the prompt template and fill in the training and test example
    prompt = params["prompt_prefix"]
    q_prefix = params["q_prefix"]
    a_prefix = params["a_prefix"]
    for s, l in zip(train_sentences, train_labels):
        prompt += q_prefix
        prompt += s + "\n"
        if isinstance(l, int) or isinstance(l, np.int32) or isinstance(l,
                                                                       np.int64):  # integer labels for classification
            assert params['task_format'] == 'classification'
            l_str = params["label_dict"][l][0] if isinstance(params["label_dict"][l], list) else params["label_dict"][l]
        else:
            assert isinstance(l, str)  # string labels
            assert params['task_format'] == 'qa'
            l_str = l

        prompt += a_prefix
        prompt += l_str + "\n\n"

    prompt += q_prefix
    prompt += test_sentence + "\n"
    assert a_prefix[-1] == ' '
    prompt += a_prefix[:-1]  # GPT models do not want a trailing space, so we cut off -1
    return prompt


def get_model_response(params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels, normalize=True, key=None):
    all_raw_answers = []
    all_logits = []
    # can optionally ignore the normal prompt and feed in a custom prompt (used for contextual calibration)
    prompts = []
    for test_sentence in test_sentences:
        prompts.append(construct_prompt(params, train_sentences, train_labels, test_sentence))

    chunked_prompts = list(chunks(prompts, chunk_size_helper(params)))
    for chunk_id, test_chunk_prompts in enumerate(chunked_prompts):
        with torch.no_grad():
            if 'gpt2' in params['model']:
                setup_gpt2(params['model'], params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels)
                logits, resp = complete_gpt2(test_chunk_prompts, params['label_dict'], normalize=normalize)
            elif 'gptj' in params['model']:
                setup_gptj(params['model'], params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels)
                logits, resp = complete_gptj(test_chunk_prompts, params['label_dict'], normalize=normalize)
            elif 'llama2_7b' in params['model']:
                setup_llama2_7b(params['model'], params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels)
                logits, resp = complete_llamma2_7b(test_chunk_prompts, params['label_dict'], normalize=normalize)
            else:
                raise NotImplementedError
        for answer_id, answer in enumerate(resp):
            all_raw_answers.append(answer)
        for logit in logits:
            all_logits.append(logit)

    return np.asarray(all_logits), np.asarray(all_raw_answers)


def params_check(params, all_train_sentences, all_train_labels, train_sentences, train_labels,  val_sentences, val_labels, test_sentences, test_labels):
    """sanity check the experiment params"""
    assert params['num_tokens_to_predict'] == 1
    if 'gpt2' in params['model']:
        setup_gpt2(params['model'], params, all_train_sentences, all_train_labels, train_sentences, train_labels, val_sentences, val_labels, test_sentences, test_labels)
    elif 'gptj' in params['model']:
        setup_gptj(params['model'], params, all_train_sentences, all_train_labels, train_sentences, train_labels,  val_sentences, val_labels, test_sentences, test_labels)
    elif 'llama2_7b' in params['model']:
        setup_llama2_7b(params['model'], params, all_train_sentences, all_train_labels, train_sentences, train_labels,  val_sentences, val_labels, test_sentences, test_labels)
    else:
        return
    # for classification, make sure that all of the class names are one word.
    for key, label_names in params['label_dict'].items():
        for label_id, label_name in enumerate(label_names):
            with torch.no_grad():
                if gpt2_tokenizer is not None:
                    input_ids = gpt2_tokenizer.encode(' ' + label_name)
                    assert len(input_ids) == 1, 'label name is more than 1 token'
                elif gptj_tokenizer is not None:
                    input_ids = gptj_tokenizer.encode(' ' + label_name)
                    assert len(input_ids) == 1, 'label name is more than 1 token'
                    # print("input_ids", input_ids)
                elif llamma2_7b_tokenizer is not None:
                    input_ids = llamma2_7b_tokenizer.encode(' ' + label_name)[2]
                    assert len([input_ids]) == 1, 'label name is more than 1 token'
                else:
                    assert len(input_ids) == 1, 'label name is more than 1 token'

    if not (params['dataset'] in ['rte', 'cb', 'align_ethical']):
        # formatting: there should be a space after question/answer prefix
        assert params["q_prefix"][-1] == " "
        assert params["a_prefix"][-1] == " "
        assert len(params["prompt_prefix"]) == 0 or params["prompt_prefix"][-2:] == '\n\n'


def load_pickle(params):
    # load saved results from model
    file_name = os.path.join(SAVE_DIR, f"{params['expr_name']}.pkl")
    assert os.path.isfile(file_name), f"file does not exist: {file_name}"
    with open(file_name, 'rb') as file:
        data = pickle.load(file)
    print(f"Loaded data from {file_name}")
    return data

def save_pickle(params, data):
    # save results from model
    file_name = os.path.join(SAVE_DIR, f"{params['expr_name']}.pkl")
    if os.path.isfile(file_name):
        print("WARNING! overwriting existing saved files")
    with open(file_name, 'wb') as file:
        pickle.dump(data, file)
    print(f"Saved to {file_name}")
    return data

def print_results(tree, names=('Original Accuracy  ','Calibrated Accuracy')):
    # print out all results
    root = deepcopy(tree)
    for dataset in root.keys():
        print(f"\n\nDataset: {dataset}")
        models_node = root[dataset]
        for model in models_node.keys():
            print(f"\nModel: {model}")
            num_shots_node = models_node[model]
            for num_shots in num_shots_node.keys():
                accuracies = np.array(list(num_shots_node[num_shots].values()))
                accuracies_mean = np.mean(accuracies, axis=0)
                accuracies_low = np.min(accuracies, axis=0)
                accuracies_high = np.max(accuracies, axis=0)
                accuracies_std = np.std(accuracies, axis=0)

                print(f"\n{num_shots}-shot, {len(accuracies)} seeds")
                for i, (m, l, h, s) in enumerate(zip(accuracies_mean, accuracies_low, accuracies_high, accuracies_std)):
                    print(f"{names[i]} | Mean: {m:.4f}, Low: {l:.4f}, High: {h:.4f}, Std: {s:.4f}")
                print()


def load_results(params_list):
    # load saved results from model
    result_tree = dict()
    for params in params_list:
        saved_result = load_pickle(params)
        keys = [params['dataset'], params['model'], params['num_shots']]
        node = result_tree  # root
        for k in keys:
            if not (k in node.keys()):
                node[k] = dict()
            node = node[k]
        node[params['seed']] = saved_result['accuracies']
    print_results(result_tree)

