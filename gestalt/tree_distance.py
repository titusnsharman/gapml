import subprocess
import numpy as np
import typing
from typing import List
import random
import time

from scipy.stats import spearmanr
from cell_lineage_tree import CellLineageTree
from constants import RSPR_PATH

class TreeDistanceMeasurerAgg:
    """
    Aggregates tree distances
    """
    def __init__(self,
        measurer_classes: List,
        ref_tree: CellLineageTree,
        scratch_dir: str):
        """
        @param measurer_classes: list of classes (subclasses of TreeDistanceMeasurer)
                                to instantiate for tree distance measurements
                                ex. [SPRDistanceMeasurer]
        @param ref_tree: the reference tree to measure distances from
        @param scratch_dir: a scratch directory used by TreeDistanceMeasurer
        """
        self.measurers = [meas_cls(ref_tree, scratch_dir) for meas_cls in measurer_classes]

    def get_tree_dists(self, trees: List[CellLineageTree]):
        """
        @return a list of dictionaries of tree distances for each tree to the ref_tree
        """
        all_dists = []
        for tree in trees:
            tree_dists = {}
            for measurer in self.measurers:
                dist = measurer.get_dist(tree)
                tree_dists[measurer.name] = dist
            all_dists.append(tree_dists)
        return all_dists

class TreeDistanceMeasurer:
    """
    Class that measures distances btw trees -- subclass this!
    """
    def __init__(self, ref_tree: CellLineageTree, scratch_dir: str):
        """
        @param ref_tree: tree to measure dsitances from
        @param scratch_dir: a directory where files can be written to if needed
                            (not used by all subclasses)
        """
        self.ref_tree = ref_tree
        self.scratch_dir = scratch_dir

    def get_dist(self, tree: CellLineageTree):
        """
        @return single tree distance number
        """
        raise NotImplementedError("need to implement!")

    def group_trees_by_dist(self, trees: List[CellLineageTree], max_trees: int=None):
        """
        @return a dictionary mapping tree distance to a group of uniq trees
                with at most max_trees for each group
        """
        tree_group_dict = {}
        for tree in trees:
            dist = self.get_dist(tree)
            if dist in tree_group_dict:
                tree_group_dict[dist].append(tree)
            else:
                tree_group_dict[dist] = [tree]

        for dist, tree_group in tree_group_dict.items():
            tree_group_dict[dist] = self.get_uniq_trees(tree_group, max_trees=max_trees)

        return tree_group_dict

    @classmethod
    def get_uniq_trees(cls, trees: List[CellLineageTree], max_trees: int=None):
        """
        @param max_trees: find this many uniq trees at most
        @return tuple with:
                    uniq trees, at most max_trees
                    indices of these uniq trees from the original tree list
        """
        # Shuffle the trees in case we are taking the first couple trees only
        random.shuffle(trees)
        num_trees = 1
        uniq_trees = [trees[0]]
        if max_trees is not None and max_trees == 1:
            return uniq_trees

        tree_measurers = [cls(trees[0], self.scratch_dir)]
        for idx, tree in enumerate(trees[1:]):
            has_match = False
            for uniq_t, measurer in zip(uniq_trees, tree_measurers):
                dist = measurer.get_dist(tree)
                has_match = dist == 0
                if has_match:
                    break
            if not has_match:
                uniq_trees.append(tree)
                tree_measurers.append(cls(tree, self.scratch_dir))
                num_trees += 1
                if max_trees is not None and num_trees > max_trees:
                    break
        return uniq_trees

class UnrootRFDistanceMeasurer(TreeDistanceMeasurer):
    """
    Robinson foulds distance, unrooted trees
    """
    name = "ete_rf_unroot"
    def get_dist(self, tree):
        rf_res = self.ref_tree.robinson_foulds(
                tree,
                attr_t1="allele_events_list_str",
                attr_t2="allele_events_list_str",
                expand_polytomies=False,
                unrooted_trees=True)
        return rf_res[0]

class RootRFDistanceMeasurer(TreeDistanceMeasurer):
    """
    Robinson foulds distance, rooted trees
    """
    name = "ete_rf_root"
    def get_dist(self, tree):
        try:
            rf_res = self.ref_tree.robinson_foulds(
                    tree,
                    attr_t1="allele_events_list_str",
                    attr_t2="allele_events_list_str",
                    expand_polytomies=False,
                    unrooted_trees=False)
            return rf_res[0]
        except Exception as err:
            logging.info("cannot get root RF distance: %s", str(err))
            return np.NaN

class SPRDistanceMeasurer(TreeDistanceMeasurer):
    """
    SPR distance
    """
    name = "spr"
    def get_dist(self, tree):
        """
        Run rspr software from Chris Whidden
        Chris's software requires that the first tree be bifurcating.
        Second tree can be multifurcating.
        """
        # Set node name to allele_events_list_str
        for n in self.ref_tree.traverse():
            n.name = n.allele_events_list_str
            if not n.is_leaf() and len(n.get_children()) != 2:
                raise ValueError("Reference tree is not binary. SPR will not work")

        for n in tree.traverse():
            n.name = n.allele_events_list_str

        # Write tree out in newick format
        suffix = "%d%d" % (int(time.time()),np.random.randint(1000000))
        tree_in_file = "%s/tree_newick%s.txt" % (
                self.scratch_dir, suffix)
        with open(tree_in_file, "w") as f:
            f.write(self.ref_tree.write(format=9))
            f.write("\n")
            f.write(tree.write(format=9))
            f.write("\n")

        # Run rspr
        rspr_out_file = "%s/tree_spr%s.txt" % (self.scratch_dir, suffix)
        subprocess.check_output(
                "%s -fpt < %s > %s" % (RSPR_PATH, tree_in_file, rspr_out_file),
                shell=True)

        # Read rspr output, distance is on the last line
        with open(rspr_out_file, "r") as f:
            lines = f.readlines()
            spr_dist = int(lines[-1].split("=")[-1])

        os.remove(tree_in_file)
        os.remove(rspr_out_file)

        return spr_dist

class MRCADistanceMeasurer(TreeDistanceMeasurer):
    """
    Use mrca dist in "Mapping Phylogenetic Trees to Reveal Distinct Patterns of Evolution", Kendall and Colijn
    """
    name = "mrca"
    def __init__(self, ref_tree: CellLineageTree, scratch_dir: str = None):
        self.ref_tree = ref_tree
        self.scratch_dir = scratch_dir

        # Number the leaves because we need to represent each tree by its pairwise
        # MRCA distance matrix
        leaf_str_sorted = sorted([leaf.allele_events_list_str for leaf in ref_tree])
        self.leaf_dict = {}
        for idx, leaf_str in enumerate(leaf_str_sorted):
            self.leaf_dict[leaf_str] = idx
        self.num_leaves = len(ref_tree)

        self.ref_tree_mrca_matrix = self._get_mrca_matrix(ref_tree)

    def _get_mrca_matrix(self, tree):
        """
        @return the pairwise MRCA distance matrix for that tree
        """
        mrca_matrix = np.zeros((self.num_leaves, self.num_leaves))
        for leaf1 in tree:
            for leaf2 in tree:
                leaf1_idx = self.leaf_dict[leaf1.allele_events_list_str]
                leaf2_idx = self.leaf_dict[leaf2.allele_events_list_str]
                if leaf1_idx == leaf2_idx:
                    # Instead of distance to itself, set this to be pendant edge length
                    mrca_matrix[leaf1_idx, leaf2_idx] = leaf1.dist
                    continue
                elif (mrca_matrix[leaf1_idx, leaf2_idx] + mrca_matrix[leaf2_idx, leaf1_idx]) > 0:
                    # We already filled this distance out
                    continue
                mrca = leaf1.get_common_ancestor(leaf2)
                mrca_dist = leaf1.get_distance(mrca)
                mrca_matrix[min(leaf1_idx, leaf2_idx), max(leaf1_idx, leaf2_idx)] = mrca_dist
        return mrca_matrix

    def get_dist(self, tree):
        tree_mrca_matrix = self._get_mrca_matrix(tree)
        norm_diff = np.linalg.norm(self.ref_tree_mrca_matrix - tree_mrca_matrix, ord="fro")
        num_entries = (self.num_leaves - 1) * self.num_leaves / 2 + self.num_leaves
        return norm_diff/np.sqrt(num_entries)

class MRCASpearmanMeasurer(MRCADistanceMeasurer):
    """
    Using rank correlation of the MRCA distance matrix
    This is an adhoc measure, but maybe provides a good idea
    """
    name = "mrca_spearman"
    @staticmethod
    def get_upper_half(matrix):
        m_shape = matrix.shape[0]
        return np.array([matrix[i,j] for i in range(m_shape) for j in range(i, m_shape)])

    def get_dist(self, tree):
        tree_mrca_matrix = self._get_mrca_matrix(tree)
        tree_mrca_matrix_half = MRCASpearmanMeasurer.get_upper_half(tree_mrca_matrix)
        ref_mrca_matrix_half = MRCASpearmanMeasurer.get_upper_half(self.ref_tree_mrca_matrix)
        spearman_corr, _ = spearmanr(tree_mrca_matrix_half, ref_mrca_matrix_half)
        return spearman_corr