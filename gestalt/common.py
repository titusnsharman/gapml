import numpy as np
import pickle
import logging

import itertools
from typing import List, Tuple, Dict

from tree_distance import get_spr_dist, MRCADistMeasurer
from constants import COLORS

def get_color(cell_type):
    if cell_type is None:
        return "lightgray"
    return COLORS[cell_type - 1]

def product_list(iterables, repeat):
    return [list(b) for b in itertools.product(iterables, repeat=repeat)]

def sigmoid(x: float):
    return 1.0/(1.0 + np.exp(-x))

def inv_sigmoid(prob: float):
    """
    @return x for prob = 1/(1 + exp(-x))
    """
    return -np.log(np.divide(1.0, prob) - 1.0)

def save_model_data(file_name, model_vars, cell_type_tree, obs_leaves, true_tree, clt):
    with open(file_name, "wb") as f:
        pickle.dump({
            "model_vars": model_vars,
            "cell_type_tree": cell_type_tree,
            "obs_leaves": obs_leaves,
            "true_tree": true_tree,
            "clt": clt,
        }, f, protocol=-1)

def save_fitted_models(
        file_name,
        fitted_results):
    """
    @param file_name: str, file to save to
    @param fitted_models_dict: dictionary mapping rf distance to a list of
                tuples. Each tuple has its first elem as the penalized log lik score
                and the second elem as the CLTLikelihoodEstimator

    Pickles the models (while avoiding tensorflow unhappiness)
    """
    res_dict = []
    for pen_log_lik, rooted_rf, unrooted_rf, res_model in fitted_results:
        res_dict.append((pen_log_lik,
                    rooted_rf,
                    unrooted_rf,
                    res_model.get_vars_as_dict()))

    with open(file_name, "wb") as f:
        pickle.dump(res_dict, f, protocol=-1)

def get_rf_dist_allele_str(tree, ref_tree, unroot=False):
    """
    For calling ete3's RF distance calculator
    """
    rf_res = ref_tree.robinson_foulds(
            tree,
            attr_t1="allele_events_list_str",
            attr_t2="allele_events_list_str",
            expand_polytomies=False,
            unrooted_trees=unroot)
    return rf_res[0]
