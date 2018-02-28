from ete3 import TreeNode
import numpy as np

class CollapsedTree:
    @staticmethod
    def _preprocess(raw_tree:TreeNode):
        tree = raw_tree.copy()
        tree.ladderize()
        return tree

    @staticmethod
    def collapse_zero_lens(raw_tree: TreeNode, feature_name: str = "observed"):
        tree = CollapsedTree._preprocess(raw_tree)
        # remove zero-length edges
        for node in tree.traverse(strategy='postorder'):
            if not hasattr(node, feature_name):
                node.add_feature(feature_name, node.is_leaf())
            if node.dist == 0 and not node.is_root():
                # TODO: one day we might want to think about collapsing only if the cell states are the same
                up_node = node.up
                up_node.name = node.name
                node.delete(prevent_nondicotomic=False)
                up_node.add_feature(feature_name, getattr(node, feature_name))
        return tree

    @staticmethod
    def collapse_zero_leaves(raw_tree: TreeNode):
        tree = CollapsedTree._preprocess(raw_tree)
        # remove zero-length edges to leaves
        for node in tree:
            if node.dist == 0:
                # TODO: one day we might want to think about collapsing only if the cell states are the same
                node.up.name = node.name
                node.delete(prevent_nondicotomic=False)
        return tree

    @staticmethod
    def collapse_same_ancestral(raw_tree: TreeNode, feature_name: str = "observed"):
        """
        @param feature_name: This feature will be attached to each node
                            The leaf nodes will have this feature be true
                            When collapsing leaf nodes into the tree, the upper node will
                            keep this feature. This is useful for understanding which nodes
                            were collapsed from the leaves.
        """
        tree = CollapsedTree._preprocess(raw_tree)
        # collapse if ancestor node has exactly the same events
        for node in tree.traverse(strategy='postorder'):
            if not hasattr(node, feature_name):
                node.add_feature(feature_name, node.is_leaf())
            if not node.is_root():
                up_node = node.up
                if node.allele_events.events == node.up.allele_events.events:
                    node.delete(prevent_nondicotomic=False, preserve_branch_length=True)
                    up_node.add_feature(feature_name, getattr(node, feature_name))
        return tree


    @staticmethod
    def collapse_first_appear(raw_tree: TreeNode, feature_name: str = "observed"):
        tree = CollapsedTree._preprocess(raw_tree)
        # collapse to subtree to first appearance of each leaf
        did_something = True
        while did_something:
            did_something = False
            for leaf in tree:
                if not leaf.is_root() and leaf.allele_events.events == leaf.up.allele_events.events:
                    # There is no branch length to preserve since this is a leaf...
                    leaf.delete(prevent_nondicotomic=False, preserve_branch_length=False)
                    did_something = True

        for node in tree.get_descendants(strategy="postorder"):
            if len(node.get_children()) == 1 and node.up.allele_events.events == node.allele_events.events:
                node.delete(prevent_nondicotomic=True, preserve_branch_length=True)

        return tree
