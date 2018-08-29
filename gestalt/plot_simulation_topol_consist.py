import os
import json
import six
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt

from tree_distance import *
from cell_lineage_tree import CellLineageTree
import plot_simulation_common

np.random.seed(0)

model_seed = 200 # 510
seeds = [500] #range(500,503)
num_barcodes = [1]
prefix = ""
growth_stage = "larval" # "lambda_diff"
tree_idx = 1
do_plots = False

TEMPLATE = "%ssimulation_topol_consist/_output/model_seed%d/%d/%s/num_barcodes%d/tune_fitted.pkl"
RAND_TEMPLATE = "%ssimulation_topol_consist/_output/model_seed%d/%d/%s/num_barcodes%d/parsimony_tree0.pkl"
TRUE_TEMPLATE = "%ssimulation_topol_consist/_output/model_seed%d/%d/%s/true_model.pkl"
OUT_TRUE_TREE_PLOT = "/Users/jeanfeng/Desktop/true_tree.png"
OUT_FITTED_TREE_PLOT = "/Users/jeanfeng/Desktop/fitted_tree%d.png"
OUT_NODE_PLOT = "/Users/jeanfeng/Desktop/node_heights.png"

def get_true_model(seed, n_bcodes, _):
    file_name = TRUE_TEMPLATE % (prefix, model_seed, seed, growth_stage)
    return plot_simulation_common.get_true_model(file_name, None, n_bcodes)

def get_result(seed, n_bcodes, _):
    res_file = TEMPLATE % (prefix, model_seed, seed, growth_stage, n_bcodes)
    return plot_simulation_common.get_result(res_file)

def get_rand_tree(seed, n_bcodes, _):
    res_file = RAND_TEMPLATE % (prefix, model_seed, seed, growth_stage, n_bcodes)
    return plot_simulation_common.get_rand_tree(res_file)


plot_simulation_common.gather_results(
        get_true_model,
        get_result,
        get_rand_tree,
        seeds,
        num_barcodes,
        n_bcode = None,
        tree_idx = tree_idx,
        do_plots = do_plots,
        num_rands = 10,
        print_keys = [
            "bhv",
            "random_bhv",
            "zero_bhv",
            "super_zero_bhv",
            "internal_corr",
            "internal_random_corr",
            "targ",
            #"double"
            ],
        out_true_tree_plot = OUT_TRUE_TREE_PLOT,
        out_fitted_tree_plot = OUT_FITTED_TREE_PLOT,
        out_node_height_plot = OUT_NODE_PLOT,
        setting_name= "barcodes")

#ONE_TREE_TEMPLATE = "%ssimulation_topol_consist/_output/model_seed%d/%d/lambda_diff/num_barcodes%d/tune_example_refitnew_tree0.pkl" % (prefix, model_seed, seeds[0], 3)
#ONE_TREE_PLOT_TEMPLATE = "%ssimulation_topol_consist/_output/model_seed%d/%d/lambda_diff/num_barcodes%d/tune_example_refitnew_tree0.png" % (prefix, model_seed, seeds[0], 3)
#with open(ONE_TREE_TEMPLATE, "rb") as f:
#    result = six.moves.cPickle.load(f)
#
#dist_key = "bhv"
#Y_bhv = []
#Y_pen_log_lik = []
#X_iters = []
#for train_iter_res in result["raw"].train_history:
#    if 'tree_dists' in train_iter_res:
#        Y_bhv.append(train_iter_res['tree_dists'][dist_key])
#        Y_pen_log_lik.append(train_iter_res['pen_log_lik'])
#        X_iters.append(train_iter_res['iter'])
#last_raw_iter = X_iters[-1]
#for train_iter_res in result["refit"].train_history:
#    if 'tree_dists' in train_iter_res:
#        Y_bhv.append(train_iter_res['tree_dists'][dist_key])
#        Y_pen_log_lik.append(train_iter_res['pen_log_lik'])
#        X_iters.append(last_raw_iter + train_iter_res['iter'])
#
#plt.clf()
#plt.figure(1)
#plt.subplot(211)
#plt.plot(X_iters, Y_bhv)
#plt.ylabel("%s distance" % dist_key)
#plt.subplot(212)
#plt.plot(X_iters, Y_pen_log_lik)
#plt.ylabel("pen log lik")
#plt.xlabel("Iterations")
#plt.savefig(ONE_TREE_PLOT_TEMPLATE)
#print(ONE_TREE_PLOT_TEMPLATE)
