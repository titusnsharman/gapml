"""
This code fits model parameters and branch lengths
constrained to the multifurcating tree topology.

Searches over bifurcating trees with the same multifurcating tree
by using a continuous parameterization.
Suppose constant events when resolving multifurcations.
"""
from __future__ import division, print_function
import os
import sys
import json
import numpy as np
import argparse
import time
import tensorflow as tf
from tensorflow.python import debug as tf_debug
from scipy.stats import pearsonr
import logging
import six

from transition_wrapper_maker import TransitionWrapperMaker
from likelihood_scorer import LikelihoodScorer
from plot_mrca_matrices import plot_mrca_matrix
from tree_distance import *
from constants import *
from common import *

def parse_args():
    parser = argparse.ArgumentParser(description='fit topology and branch lengths for GESTALT')
    parser.add_argument(
        '--obs-file',
        type=str,
        default="_output/obs_data.pkl",
        help='pkl file with observed sequence data, should be a dict with ObservedAlignSeq')
    parser.add_argument(
        '--topology-file',
        type=str,
        default="_output/parsimony_tree0.pkl",
        help='pkl file with tree topology')
    parser.add_argument(
        '--true-model-file',
        type=str,
        default=None,
        help='pkl file with true model if available')
    parser.add_argument(
        '--true-collapsed-tree-file',
        type=str,
        default=None,
        help='pkl file with collapsed tree if available')
    parser.add_argument(
        '--seed',
        type=int,
        default=40)
    parser.add_argument(
        '--log-barr',
        type=float,
        default=0.001,
        help="log barrier parameter on the branch lengths")
    parser.add_argument(
        '--target-lam-pen',
        type=float,
        default=0.1,
        help="penalty parameter on the target lambdas")
    parser.add_argument('--max-iters', type=int, default=20)
    parser.add_argument('--num-inits', type=int, default=1)
    parser.add_argument(
        '--do-refit',
        action='store_true',
        help='refit after tuning over the compatible bifurcating trees')
    parser.add_argument(
        '--max-sum-states',
        type=int,
        default=None,
        help='maximum number of internal states to marginalize over')
    parser.add_argument(
        '--max-extra-steps',
        type=int,
        default=1,
        help='maximum number of extra steps to explore possible ancestral states')
    parser.add_argument(
        '--scratch-dir',
        type=str)

    parser.set_defaults(is_refit=False)
    args = parser.parse_args()
    args.log_file = args.topology_file.replace(".pkl", "_fit_log.txt")
    print("Log file", args.log_file)
    args.pickle_out = args.topology_file.replace(".pkl", "_fitted.pkl")
    args.json_out = args.topology_file.replace(".pkl", "_fitted.json")
    args.out_folder = os.path.dirname(args.topology_file)

    assert args.log_barr >= 0
    assert args.target_lam_pen >= 0
    return args

def main(args=sys.argv[1:]):
    args = parse_args()
    logging.basicConfig(format="%(message)s", filename=args.log_file, level=logging.DEBUG)
    logging.info(str(args))

    np.random.seed(seed=args.seed)

    with open(args.obs_file, "rb") as f:
        obs_data_dict = six.moves.cPickle.load(f)
        bcode_meta = obs_data_dict["bcode_meta"]
        obs_leaves = obs_data_dict["obs_leaves"]
        tot_time = obs_data_dict["time"]
    logging.info("Number of uniq obs alleles %d", len(obs_leaves))
    logging.info("Barcode cut sites %s", str(bcode_meta.abs_cut_sites))

    with open(args.topology_file, "rb") as f:
        tree_topology_info = six.moves.cPickle.load(f)
        if args.is_refit:
            tree = tree_topology_info.fitted_bifurc_tree
        else:
            tree = tree_topology_info["tree"]
    tree.label_node_ids()
    logging.info("Tree topology info: %s", tree_topology_info)
    logging.info("Tree topology num leaves: %d", len(tree))

    has_unresolved_multifurcs = False
    for node in tree.traverse():
        if not node.is_resolved_multifurcation():
            has_unresolved_multifurcs = True
            break
    logging.info("Tree has unresolved mulfirucs? %d", has_unresolved_multifurcs)

    true_model_dict = None
    oracle_dist_measurers = None
    if args.true_model_file is not None and args.true_collapsed_tree_file is not None:
        with open(args.true_collapsed_tree_file, "rb") as f:
            collapsed_true_subtree = six.moves.cPickle.load(f)
        with open(args.true_model_file, "rb") as f:
            true_model_dict = six.moves.cPickle.load(f)

        oracle_dist_measurers = TreeDistanceMeasurerAgg([
            UnrootRFDistanceMeasurer,
            RootRFDistanceMeasurer,
            #SPRDistanceMeasurer,
            MRCADistanceMeasurer,
            MRCASpearmanMeasurer],
            collapsed_true_subtree,
            args.scratch_dir)

    sess = tf.InteractiveSession()
    tf.global_variables_initializer().run()

    transition_wrap_maker = TransitionWrapperMaker(
            tree,
            bcode_meta,
            args.max_extra_steps,
            args.max_sum_states)

    worker = LikelihoodScorer(
       args.seed,
       tree,
       bcode_meta,
       args.log_barr,
       args.target_lam_pen,
       args.max_iters,
       args.num_inits,
       transition_wrap_maker,
       init_model_params = {
           "target_lams": 0.04 * np.ones(bcode_meta.n_targets) + np.random.uniform(size=bcode_meta.n_targets) * 0.02,
           "tot_time": tot_time},
       dist_measurers = oracle_dist_measurers)

    raw_res = worker.do_work_directly(sess)
    refit_res = None

    if not has_unresolved_multifurcs:
        refit_res = raw_res
    elif has_unresolved_multifurcs and args.do_refit:
        logging.info("Doing refit")
        # Now we need to refit using the bifurcating tree
        # Copy over the latest model parameters for warm start
        param_dict = {k: v for k,v in raw_res.model_params_dict.items()}
        refit_bifurc_tree = raw_res.fitted_bifurc_tree.copy()
        refit_bifurc_tree.label_node_ids()
        num_nodes = refit_bifurc_tree.get_num_nodes()
        # Copy over the branch lengths
        br_lens = np.zeros(num_nodes)
        for node in refit_bifurc_tree.traverse():
            br_lens[node.node_id] = node.dist
            node.resolved_multifurcation = True
        param_dict["branch_len_inners"] = br_lens
        param_dict["branch_len_offsets_proportion"] = np.zeros(num_nodes)
        # Create the new likelihood worker and make it work!
        refit_transition_wrap_maker = TransitionWrapperMaker(
                refit_bifurc_tree,
                bcode_meta,
                args.max_extra_steps,
                args.max_sum_states)
        refit_worker = LikelihoodScorer(
                args.seed + 1,
                refit_bifurc_tree,
                bcode_meta,
                args.log_barr,
                args.target_lam_pen,
                args.max_iters,
                args.num_inits,
                refit_transition_wrap_maker,
                init_model_params = param_dict,
                dist_measurers = oracle_dist_measurers)
        refit_res = refit_worker.do_work_directly(sess)

    #### Mostly a section for printing
    res = refit_res if refit_res is not None else raw_res
    print(res.model_params_dict)
    logging.info(res.fitted_bifurc_tree.get_ascii(attributes=["node_id"], show_internal=True))
    logging.info(res.fitted_bifurc_tree.get_ascii(attributes=["dist"], show_internal=True))
    logging.info(res.fitted_bifurc_tree.get_ascii(attributes=["allele_events_list_str"], show_internal=True))
    logging.info(res.fitted_bifurc_tree.get_ascii(attributes=["cell_state"]))

    # Also create a dictionaty as a summary of what happened
    if oracle_dist_measurers is not None:
        result_print_dict = oracle_dist_measurers.get_tree_dists([res.fitted_bifurc_tree])[0]
        true_target_lambdas = true_model_dict["true_model_params"]["target_lams"]
        pearson_target = pearsonr(
                true_target_lambdas,
                res.model_params_dict["target_lams"])
        result_print_dict["pearson_target_corr"] = pearson_target[0]
        result_print_dict["pearson_target_pval"] = pearson_target[1]
        result_print_dict["target_lam_dist"] = np.linalg.norm(
                true_target_lambdas - res.model_params_dict["target_lams"])
    else:
        result_print_dict = {}
    result_print_dict["log_lik"] = res.train_history[-1]["log_lik"][0]

    # Save quick summary data as json
    with open(args.json_out, 'w') as outfile:
        json.dump(result_print_dict, outfile)

    # Save the data
    with open(args.pickle_out, "wb") as f:
        save_dict = {
                "raw": raw_res,
                "refit": refit_res}
        six.moves.cPickle.dump(save_dict, f, protocol = 2)

    #plot_mrca_matrix(
    #    res.fitted_bifurc_tree,
    #    args.pickle_out.replace(".pkl", "_mrca.png"))

if __name__ == "__main__":
    main()
