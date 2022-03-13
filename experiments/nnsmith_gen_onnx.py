from nnsmith.graph_gen import random_model_gen, SymbolNet
from nnsmith.export import torch2onnx

import os
import shutil
import random
import argparse
import time
import warnings

from tqdm import tqdm
import torch

def nnsmith_gen_once(path, seed, max_nodes):
    torch.manual_seed(seed)
    gen, solution = random_model_gen(
        min_dims=[1, 3, 48, 48], # Only rank useful. Dim sizes means nothing.
        seed=seed, max_nodes=max_nodes)
    net = SymbolNet(gen.abstract_graph, solution, verbose=False, alive_shapes=gen.alive_shapes)
    with torch.no_grad():
        net.eval()
        torch2onnx(net, path, verbose=False, use_cuda=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--onnx_dir', type=str, required=True)
    parser.add_argument('--time_budget', type=int, default=60 * 60 * 4)
    parser.add_argument('--max_nodes', type=int, default=10)
    args = parser.parse_args()

    if os.path.exists(args.onnx_dir):
        # TODO: Allow continous fuzzing...
        decision = ''
        while decision.lower() not in ['y', 'n']:
            decision = input(
                'Report folder already exists. Press [Y/N] to continue or exit...')
        if decision.lower() == 'n':
            raise RuntimeError(
                f'{args.onnx_dir} already exist... We want an empty folder to report...')
        else:
            shutil.rmtree(args.onnx_dir)

    os.mkdir(args.onnx_dir)

    # FORMAT: {generation time cost in seconds}, {model relative path}
    # MUST RANK by GENERATION ORDER.
    config_file = open(os.path.join(args.onnx_dir, 'gentime.csv'), 'w')

    start_time = time.time()
    gen_cnt = 0
    valid_cnt = 0

    with tqdm(total=args.time_budget) as pbar:
        while time.time() - start_time < args.time_budget:
            seed = random.getrandbits(32)
            to_name = f'{valid_cnt}.onnx'

            tstart = time.time()
            try:
                with warnings.catch_warnings(): # just shutup.
                    warnings.simplefilter("ignore")
                    nnsmith_gen_once(os.path.join(args.onnx_dir, to_name), seed, max_nodes=10)
                label = to_name
                valid_cnt += 1
            except Exception as e:
                print(f'Fail when seed={seed}')
                print(e)
                label = 'FAILURE'
            
            time_diff = time.time() - tstart
            config_file.write(f'{time_diff:.5f},{label}\n')
            
            gen_cnt += 1
            config_file.flush()
            
            pbar.update(int(time.time() - start_time) - pbar.n)
            pbar.set_description(f'valid={valid_cnt},fail={gen_cnt-valid_cnt}')
            pbar.refresh()
        config_file.close()