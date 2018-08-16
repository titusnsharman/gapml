from typing import List, Tuple, Dict
from numpy import ndarray
import numpy as np
import tensorflow as tf
import logging

from cell_lineage_tree import CellLineageTree
from cell_state import CellTypeTree
from barcode_metadata import BarcodeMetadata
from parallel_worker import ParallelWorker
from transition_wrapper_maker import TransitionWrapperMaker
from clt_likelihood_model import CLTLikelihoodModel
from clt_likelihood_estimator import CLTPenalizedEstimator
from tree_distance import TreeDistanceMeasurerAgg
from optim_settings import KnownModelParams


class LikelihoodScorerResult:
    """
    Stores results from LikelihoodScorer below
    """
    def __init__(self, model_params_dict: Dict, fitted_bifurc_tree: CellLineageTree, train_history: List):
        self.model_params_dict = model_params_dict
        self.fitted_bifurc_tree = fitted_bifurc_tree
        self.train_history = train_history
        self.pen_log_lik = train_history[-1]["pen_log_lik"]

class LikelihoodScorer(ParallelWorker):
    """
    Fits model parameters and branch lengths for a given tree
    Since this is a parallel worker, it may be used through the job management system SLURM
    """
    def __init__(self,
            seed: int,
            tree: CellLineageTree,
            bcode_meta: BarcodeMetadata,
            log_barr: float,
            dist_to_half_pen: float,
            max_iters: int,
            num_inits: int,
            transition_wrap_maker: TransitionWrapperMaker,
            init_model_params: Dict,
            known_params: KnownModelParams,
            dist_measurers: TreeDistanceMeasurerAgg = None,
            max_try_per_init: int = 2,
            abundance_weight: float = 0):
        """
        @param seed: required to set the seed of each parallel worker
        @param tree: the cell lineage tree topology to fit the likelihood for
        @param bcode_meta: BarcodeMetadata
        @param log_barr: log barrier penalty parameter, i.e. how much to scale the penalty
        @param dist_to_half_pen: penalty parameter for penalizing how far the prob transition matrices
                                are from having 1/2 on the diagonal
        @param max_iters: maximum number of iterations for MLE
        @param transition_wrap_maker: TransitionWrapperMaker
        @param dist_measurers: if not None, TreeDistanceMeasurerAgg is used to measure the distance between the estimated
                                tree and the oracle tree at each iteration
        """
        self.seed = seed
        self.tree = tree
        self.bcode_meta = bcode_meta
        self.log_barr = log_barr
        self.dist_to_half_pen = dist_to_half_pen
        self.max_iters = max_iters
        self.num_inits = num_inits
        self.transition_wrap_maker = transition_wrap_maker
        self.init_model_params = init_model_params
        self.known_params = known_params
        self.dist_measurers = dist_measurers
        self.max_tries = max_try_per_init * num_inits
        self.abundance_weight = abundance_weight

    def run_worker(self, shared_obj):
        """
        @param shared_obj: ignored
        """
        sess = tf.Session()
        with sess.as_default():
            tf.global_variables_initializer().run()
            return self.do_work_directly(sess)

    def fit_one_init(self, estimator: CLTPenalizedEstimator, res_model: CLTLikelihoodModel, init_index: int):
        # Initialize branch lengths if not provided
        if 'branch_len_inners' not in self.init_model_params or 'branch_len_offsets_proportion' not in self.init_model_params:
            res_model.initialize_branch_lens()

        # Fill in the dictionary for initializing model params
        full_init_model_params = res_model.get_vars_as_dict()
        for key, val in self.init_model_params.items():
            if key not in ["tot_time", "tot_time_extra"] and val.shape != full_init_model_params[key].shape:
                raise ValueError(
                        "Something went wrong. not same shape for key %s (%s vs %s)" %
                        (key, val.shape, full_init_model_params[key].shape))
            full_init_model_params[key] = val
        res_model.set_params_from_dict(full_init_model_params)

        # Just checking branch lengths positive
        br_lens = res_model.get_branch_lens()[1:]
        if not np.all(br_lens > -1e-10):
            raise ValueError("not all positive %s" % br_lens)
        assert res_model._are_all_branch_lens_positive()

        # Actually fit the model
        train_history = estimator.fit(dist_measurers = self.dist_measurers)
        result = LikelihoodScorerResult(
            res_model.get_vars_as_dict(),
            res_model.get_fitted_bifurcating_tree(),
            train_history)
        logging.info("Initialization %d result: %f", init_index, result.pen_log_lik)
        logging.info(result.fitted_bifurc_tree.get_ascii(attributes=["node_id"], show_internal=True))
        logging.info(result.fitted_bifurc_tree.get_ascii(attributes=["dist"], show_internal=True))
        logging.info(result.fitted_bifurc_tree.get_ascii(attributes=["allele_events_list_str"], show_internal=True))
        return result

    def do_work_directly(self, sess):
        """
        Bypasses all the other code for a ParallelWorker
        Used when we aren't submitting jobs
        Supposes a tensorflow session is given already. Does not make a new one

        @param sess: tensorflow session

        @return LikelihoodScorerResult
        """
        np.random.seed(self.seed)
        res_model = CLTLikelihoodModel(
            self.tree,
            self.bcode_meta,
            sess,
            known_params = self.known_params,
            target_lams = self.init_model_params["target_lams"],
            boost_softmax_weights = self.init_model_params["boost_softmax_weights"],
            trim_long_factor = self.init_model_params["trim_long_factor"],
            trim_zero_probs = self.init_model_params["trim_zero_probs"],
            trim_short_poissons = self.init_model_params["trim_short_poissons"],
            trim_long_poissons = self.init_model_params["trim_long_poissons"],
            insert_zero_prob= self.init_model_params["insert_zero_prob"],
            insert_poisson= self.init_model_params["insert_poisson"],
            double_cut_weight = self.init_model_params["double_cut_weight"],
            tot_time = self.init_model_params["tot_time"],
            tot_time_extra = self.init_model_params["tot_time_extra"],
            cell_type_tree = None,
            abundance_weight = self.abundance_weight)
        estimator = CLTPenalizedEstimator(
                res_model,
                self.transition_wrap_maker,
                self.max_iters,
                self.log_barr,
                self.dist_to_half_pen)

        # Fit multiple initializations
        results = []
        for i in range(self.max_tries):
            try:
                # Note that we will be warm-starting from all the model params
                # Except that we re-initialize branch lengths.
                # Pretty reasonable assuming the target lambdas are relatively stable
                result = self.fit_one_init(estimator, res_model, i)
            except tf.errors.InvalidArgumentError as e:
                logging.info(e)
                continue
            results.append(result)
            if len(results) >= self.num_inits:
                break

        assert len(results) > 0

        # Pick out the best result
        best_res = results[0]
        for res in results:
            if res.pen_log_lik > best_res.pen_log_lik:
                best_res = res
        return best_res

    def __str__(self):
        return self.name
