import time
from tensorflow import Session
import numpy as np
import scipy.linalg
from typing import List, Tuple
from numpy import ndarray

from clt_estimator import CLTEstimator
from cell_lineage_tree import CellLineageTree
from clt_likelihood_model import CLTLikelihoodModel
import ancestral_events_finder as anc_evt_finder
from approximator import ApproximatorLB
from transition_matrix import TransitionMatrixWrapper, TransitionMatrix
from indel_sets import TargetTract

from state_sum import StateSum
from common import target_tract_repr_diff

class CLTLassoEstimator(CLTEstimator):
    """
    Likelihood estimator

    TODO: Right now this ignores cell type. we'll add it in later
    """
    def __init__(
        self,
        sess: Session,
        penalty_param: float,
        model_params: CLTLikelihoodModel,
        approximator: ApproximatorLB):
        """
        @param penalty_param: lasso penalty parameter
        @param model_params: initial CLT model params
        """
        self.sess = sess
        self.penalty_param = penalty_param
        self.model_params = model_params
        self.approximator = approximator

        # Annotate with ancestral states
        anc_evt_finder.annotate_ancestral_states(model_params.topology, model_params.bcode_meta)
        # Construct transition boolean matrix -- via state sum approximation
        self.approximator.annotate_state_sum_transitions(model_params.topology)
        # Create the skeletons for the transition matrices
        self.transition_mat_wrappers = model_params.create_transition_matrix_wrappers()

    def _initialize_transition_matrices(self, model_params: CLTLikelihoodModel):
        """
        @return a list of real transition matrices
        """
        UNLIKELY = "unlikely"
        all_matrices = dict()
        for node_id, matrix_wrapper in self.transition_mat_wrappers.items():
            # Get inputs ready for tensorflow
            hazard_list = []
            tt_evts = []
            start_tts_list = []
            for start_tts, matrix_row in matrix_wrapper.matrix_dict.items():
                start_tts_list.append(start_tts)
                for end_tts, tt_evt in matrix_row.items():
                    tt_evts.append(tt_evt)

            # Gets hazards (by tensorflow)
            hazard_aways = model_params.get_hazard_aways(start_tts_list)
            hazards = model_params.get_hazards(tt_evts)

            # Now fill in the matrix
            idx = 0
            matrix_dict = dict()
            for i, (start_tts, matrix_row) in enumerate(matrix_wrapper.matrix_dict.items()):
                matrix_dict[start_tts] = dict()
                haz_to_likely = 0
                for end_tts, tt_evt in matrix_row.items():
                    haz = hazards[idx]
                    matrix_dict[start_tts][end_tts] = haz
                    haz_to_likely += haz
                    idx += 1
                haz_away = hazard_aways[i]
                haz_to_unlikely = haz_away - haz_to_likely
                matrix_dict[start_tts][UNLIKELY] = haz_to_unlikely
                matrix_dict[start_tts][start_tts] = -haz_away


            # Add unlikely state
            matrix_dict[UNLIKELY] = dict()

            all_matrices[node_id] = TransitionMatrix(matrix_dict)
        return all_matrices


    def get_likelihood(self, model_params: CLTLikelihoodModel, get_grad: bool = False):
        """
        Does the Felsenstein algo to efficiently calculate the likelihood of the tree,
        assuming state_sum contains all the possible ancestral states (though that's not
        actually true. it's an approximation)

        @return The likelihood for proposed theta, the gradient too if requested
        """
        transition_matrices = self._initialize_transition_matrices(model_params)

        log_lik = 0
        L = dict() # Stores normalized probs
        pt_matrix = dict()
        trim_probs = dict()
        for node in model_params.topology.traverse("postorder"):
            if node.is_leaf():
                node_trans_mat = transition_matrices[node.node_id]
                L[node.node_id] = np.zeros((node_trans_mat.num_states, 1))
                assert len(node.state_sum.tts_list) == 1
                tts_key = node_trans_mat.key_dict[node.state_sum.tts_list[0]]
                L[node.node_id][tts_key] = 1
            else:
                L[node.node_id] = 1
                for child in node.children:
                    ch_trans_mat = transition_matrices[child.node_id]

                    # Get the trim probabilities
                    trim_probs[child.node_id] = self._get_trim_probs(
                            model_params,
                            ch_trans_mat,
                            node,
                            child)

                    # Create the probability matrix exp(Qt) = A * exp(Dt) * A^-1
                    branch_len = model_params.branch_lens[child.node_id].eval()
                    pt_matrix[child.node_id] = np.dot(
                            ch_trans_mat.A,
                            np.dot(
                                np.diag(np.exp(ch_trans_mat.D * branch_len)),
                                ch_trans_mat.A_inv))

                    # Get the probability for the data descended from the child node, assuming that the node
                    # has a particular target tract repr.
                    # These down probs are ordered according to the child node's numbering of the TTs states
                    ch_ordered_down_probs = np.dot(
                        np.multiply(
                            pt_matrix[child.node_id],
                            trim_probs[child.node_id]),
                        L[child.node_id])

                    if not node.is_root():
                        # Reorder summands according to node's numbering of tts states
                        node_trans_mat = transition_matrices[node.node_id]
                        down_probs = self._reorder_likelihoods(
                            ch_ordered_down_probs,
                            node.state_sum.tts_list,
                            node_trans_mat,
                            ch_trans_mat)

                        L[node.node_id] *= down_probs
                        if down_probs.max() == 0:
                            raise ValueError("Why is everything zero?")
                    else:
                        # For the root node, we just want the probability where the root node is unmodified
                        # No need to reorder
                        ch_id = ch_trans_mat.key_dict[()]
                        L[node.node_id] *= ch_ordered_down_probs[ch_id]

                scaler = L[node.node_id].max()
                if scaler == 0:
                    raise ValueError("Why is everything zero?")
                L[node.node_id] /= scaler
                log_lik += np.sum(np.log(scaler))

        log_lik += np.log(L[model_params.root_node_id])
        return log_lik

    def _get_trim_probs(self,
            model_params: CLTLikelihoodModel,
            ch_trans_mat: TransitionMatrixWrapper,
            node: CellLineageTree,
            child: CellLineageTree):
        """
        @param model_params: model parameter
        @param ch_trans_mat: the transition matrix corresponding to child node (we make sure the entries in the trim prob matrix match
                        the order in ch_trans_mat)
        @param node: the parent node
        @param child: the child node

        @return matrix of conditional probabilities of each trim
        """
        trim_prob_mat = np.ones((ch_trans_mat.num_states, ch_trans_mat.num_states))

        for node_tts in node.state_sum.tts_list:
            node_tts_key = ch_trans_mat.key_dict[node_tts]
            for child_tts in child.state_sum.tts_list:
                child_tts_key = ch_trans_mat.key_dict[child_tts]
                diff_target_tracts = target_tract_repr_diff(node_tts, child_tts)
                trim_prob = model_params.get_prob_unmasked_trims(child.anc_state, diff_target_tracts)
                trim_prob_mat[node_tts_key, child_tts_key] = trim_prob

        return trim_prob_mat

    def _reorder_likelihoods(self,
            vec_lik: ndarray,
            tts_list: List[Tuple[TargetTract]],
            node_trans_mat: TransitionMatrixWrapper,
            ch_trans_mat: TransitionMatrixWrapper):
        """
        @param vec_lik: the thing to be re-ordered
        @param tts_list: list of target tract reprs to include in the vector
                        rest can be set to zero
        @param node_trans_mat: provides the desired ordering
        @param ch_trans_mat: provides the ordering used in vec_lik

        @return the reordered version of vec_lik according to the order in node_trans_mat
        """
        down_probs = np.zeros((node_trans_mat.num_states, 1))
        for tts in tts_list:
            ch_tts_id = ch_trans_mat.key_dict[tts]
            node_tts_id = node_trans_mat.key_dict[tts]
            down_probs[node_tts_id] = vec_lik[ch_tts_id]
        return down_probs
