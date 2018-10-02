import numpy as np
import sys
import argparse
import os
import six
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import seaborn as sns

from cell_lineage_tree import CellLineageTree
from common import parse_comma_str
import file_readers
from tree_distance import TreeDistanceMeasurerAgg
from plot_simulation_topol_consist import get_true_model, get_mle_result, get_chronos_result


def parse_args(args):
    parser = argparse.ArgumentParser(
            description='tune over topologies and fit model parameters')
    parser.add_argument(
        '--true-model-file-template',
        type=str,
        default="tmp_mount/simulation_topol_consist/_output/model_seed%d/%d/%s/true_model.pkl")
    parser.add_argument(
        '--mle-file-template',
        type=str,
        default="tmp_mount/simulation_topol_consist/_output/model_seed%d/%d/%s/num_barcodes%d/sum_states_10/extra_steps_1/tune_fitted.pkl")
    parser.add_argument(
        '--chronos-file-template',
        type=str,
        default="tmp_mount/simulation_topol_consist/_output/model_seed%d/%d/%s/num_barcodes%d/chronos_fitted.pkl")
    parser.add_argument(
        '--model-seed',
        type=int,
        default=100)
    parser.add_argument(
        '--data-seeds',
        type=str,
        default="200")
    parser.add_argument(
        '--n-bcodes-list',
        type=str,
        default="1,2,4")
    parser.add_argument(
        '--growth-stage',
        type=str,
        default="small")
    parser.add_argument(
        '--out-plot-template',
        type=str,
        default="_output/simulation_tree_%d_%d_%s.png")
    parser.add_argument(
        '--scratch-dir',
        type=str,
        default="_output/scratch")

    parser.set_defaults()
    args = parser.parse_args(args)

    if not os.path.exists(args.scratch_dir):
        os.mkdir(args.scratch_dir)

    args.data_seeds = parse_comma_str(args.data_seeds, int)
    args.n_bcodes_list = parse_comma_str(args.n_bcodes_list, int)
    return args

def plot_tree(
        tree: CellLineageTree,
        ref_tree: CellLineageTree,
        file_name: str = "",
        width: int=300,
        show_leaf_name: bool = True):
    from ete3 import CircleFace, TreeStyle, NodeStyle, RectFace
    print(file_name)
    tree.ladderize()
    ref_tree.ladderize()

    nstyle = NodeStyle()
    nstyle["size"] = 0
    for n in tree.traverse():
        if not n.is_leaf():
            n.set_style(nstyle)

    leaf_dict = {}
    for leaf_idx, leaf in enumerate(ref_tree):
        leaf_dict[leaf.leaf_key] = leaf_idx
    for leaf_idx, leaf in enumerate(tree):
        leaf.name = "%d" % leaf_dict[leaf.leaf_key]
    print(len(tree), len(ref_tree))
    assert len(tree) == len(ref_tree)

    tree.show_leaf_name = show_leaf_name

    tree.show_branch_length = True
    ts = TreeStyle()
    ts.scale = 100

    tree.render(file_name, w=width, units="mm", tree_style=ts)
    print("done")

def main(args=sys.argv[1:]):
    args = parse_args(args)

    for n_bcodes in args.n_bcodes_list:
        print("barcodes", n_bcodes)
        for seed in args.data_seeds:
            print("seed", seed)
            true_params, assessor = get_true_model(args, seed, n_bcodes)
            mle_params, mle_tree = get_mle_result(args, seed, n_bcodes)
            full_mle_tree = TreeDistanceMeasurerAgg.create_single_abundance_tree(mle_tree, "leaf_key")
            full_tree_assessor = assessor._get_full_tree_assessor(mle_tree)
            _, chronos_tree = get_chronos_result(args, seed, n_bcodes, assessor)
            full_chronos_tree = TreeDistanceMeasurerAgg.create_single_abundance_tree(chronos_tree, "leaf_key")

            if n_bcodes == args.n_bcodes_list[0]:
                plot_tree(
                    full_tree_assessor.ref_tree,
                    full_tree_assessor.ref_tree,
                    args.out_plot_template % (0, seed, "true"))

            plot_tree(
                full_mle_tree,
                full_tree_assessor.ref_tree,
                args.out_plot_template % (n_bcodes, seed, "mle"))

            plot_tree(
                full_chronos_tree,
                full_tree_assessor.ref_tree,
                args.out_plot_template % (n_bcodes, seed, "chronos"))

if __name__ == "__main__":
    main()
