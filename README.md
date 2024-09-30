# Enhancing In-context Learning via Linear Probe Calibration [AISTATS 2024]

[![paper](https://img.shields.io/badge/arXiv-Paper-<COLOR>.svg)](https://arxiv.org/abs/2401.12406)

This codebase is compatible with GPT-2, GPT-J, Llama-2, and any other language model available in [HuggingFace Transformers](https://huggingface.co/models).

## Dependencies

The code is implemented using PyTorch and the [HuggingFace's Transformer repository](https://github.com/huggingface/pytorch-transformers). If you intend to run the code on a small local model like GPT-2, it necessitates a single GPU.

## Installation
To setup the anaconda environment, simply run the following command:
```
conda env create -f setup_environment.yaml
```

After installation is complete, run:
```
conda activate fewshot_a10
```

## Datasets
We provide evaluation support for SST-2, SST-5, AGNews, TREC, DBPedia, RTE, and Subj datasets. You have the flexibility to incorporate additional text-classification datasets by defining the prompt format and label space in a manner similar to the existing datasets in data_utils.py.

## Evaluation
You can replicate the results in our paper by running the example sh scripts in the `examples_ssh` folder. For example, to run SST-2 0-shot on GPT-J, run: `sh examples_ssh/cls_sst2_gptj_0shot.sh`. Alternatively, copy and paste the contents of the .sh file into the terminal as follows:

```
python run_classification.py \
--model="gptj" \
--dataset="sst2" \
--num_seeds=5 \
--all_shots="0" \
--subsample_test_set=300 \
--epochs=15 \
--lr=0.015 \
--val_size=100 \
--val_seed=20230307
```

To execute different experiments, specify the desired arguments in the above command from the corresponding .sh file. For any other experiment, follow settings from the paper. 

## Citation
If you find our work, or this repository useful, please consider giving a star :star: and citation.
```bibtex

@InProceedings{pmlr-v238-abbas24a,
  title = 	 { Enhancing In-context Learning via Linear Probe Calibration },
  author =       {Abbas, Momin and Zhou, Yi and Ram, Parikshit and Baracaldo, Nathalie and Samulowitz, Horst and Salonidis, Theodoros and Chen, Tianyi},
  booktitle = 	 {Proceedings of The 27th International Conference on Artificial Intelligence and Statistics},
  year = 	 {2024}
}

```

## Contact
Should you have any inquiries, reach out to us via email at abbasm2@rpi.edu.


## Acknowledgements

Our code is built upon [Contextual Calibration](https://github.com/tonyzhaozh/few-shot-learning) repository, and we extend our appreciation to the authors for sharing their code. Should you decide to use our model and code, please consider citing their work as well.



## Running Baselines:
Test:
CUDA_VISIBLE_DEVICES=0 python run_baselines/run_classification.py --model="llama2_13b" --dataset="response_beavertails_unethical_OOD_mbpp"

Train:
CUDA_VISIBLE_DEVICES=0 python run_baselines/run_classification.py --model="llama2_13b" --dataset="response_beavertails_unethical_OOD_mbpp" --train

After training the checkpoints will be saved in the 'saved_checkpoints' folder. Load the checkpoint by changing the 'folder_name' in setup_llama2_13b function in the utils.py file.

## Running Ours:
Test:
CUDA_VISIBLE_DEVICES=0 python run_baselines/run_classification.py --model="llama2_13b" --dataset="civil_comments_toxicity_OOD_toxigen"

Train:
CUDA_VISIBLE_DEVICES=0 python run_baselines/run_classification.py --model="llama2_13b" --dataset="civil_comments_toxicity_OOD_toxigen" --train


## Running Selective Classification:
CUDA_VISIBLE_DEVICES=0 python run_selective_classification/run_classification.py --model="ll
ama2_7b" --dataset="response_beavertails_unethical_OOD_sexual-drug" --coverage=0.2 --method='synthetic'

## Running RLHF Rewar model filtering:
CUDA_VISIBLE_DEVICES=0 python run_RLHF_reward/reward_bench_train_original.py
CUDA_VISIBLE_DEVICES=0 python run_RLHF_reward/reward_bench_train_synthetic.py
