# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#
################################################################################

"""
This file contains a helper class to build the ResNet models.
It implements the following things by exposing all the hyperparams:
1. Bottleneck block of Resnet
4. Layer (which combines multiple blocks of one type)
5. Shortcut: only type B
"""

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import division

from self_supervision_benchmark.core.config import config as cfg


class ModelHelper():

    def __init__(self, model, split):
        self.model = model
        self.split = split

    def get_test_mode(self):
        test_mode = False
        if self.split in ['test', 'val'] or cfg.MODEL.FORCE_BN_TEST_MODE:
            test_mode = True
        return test_mode

    # shortcut type B
    def add_shortcut(self, blob_in, dim_in, dim_out, stride, prefix):
        if dim_in == dim_out:
            return blob_in
        conv_blob = self.model.Conv(
            blob_in, prefix, dim_in, dim_out, kernel=1, stride=stride,
            weight_init=("MSRAFill", {}),
            bias_init=('ConstantFill', {'value': 0.}), no_bias=1
        )
        test_mode = self.get_test_mode()
        bn_blob = self.model.SpatialBN(
            conv_blob, prefix + "_bn", dim_out, epsilon=cfg.MODEL.BN_EPSILON,
            momentum=cfg.MODEL.BN_MOMENTUM, is_test=test_mode,
        )
        return bn_blob

    def conv_bn(
        self, blob_in, dim_in, dim_out, kernel, stride, prefix, group=1, pad=1,
    ):
        conv_blob = self.model.Conv(
            blob_in, prefix, dim_in, dim_out, kernel, stride=stride,
            pad=pad, group=group,
            weight_init=("MSRAFill", {}),
            bias_init=('ConstantFill', {'value': 0.}), no_bias=1
        )
        test_mode = self.get_test_mode()
        bn_blob = self.model.SpatialBN(
            conv_blob, prefix + "_bn", dim_out, epsilon=cfg.MODEL.BN_EPSILON,
            momentum=cfg.MODEL.BN_MOMENTUM, is_test=test_mode,
        )
        return bn_blob

    def conv_bn_relu(
        self, blob_in, dim_in, dim_out, kernel, stride, prefix, pad=1, group=1,
    ):
        bn_blob = self.conv_bn(
            blob_in, dim_in, dim_out, kernel, stride, prefix, group=group,
            pad=pad
        )
        if cfg.MODEL.ALLOW_INPLACE_RELU:
            relu_blob = self.model.Relu(bn_blob, bn_blob)
        else:
            relu_blob = self.model.Relu(bn_blob, prefix + "_relu")
        return relu_blob

    # bottleneck residual layer for 18, 34, 50, 101, 152 layer networks
    def bottleneck_block(
        self, blob_in, dim_in, dim_out, stride, prefix, dim_inner, group=None
    ):
        blob_out = self.conv_bn_relu(
            blob_in, dim_in, dim_inner, 1, 1, prefix + "_branch2a", pad=0,
        )
        blob_out = self.conv_bn_relu(
            blob_out, dim_inner, dim_inner, 3, stride, prefix + "_branch2b",
        )
        bn_blob = self.conv_bn(
            blob_out, dim_inner, dim_out, 1, 1, prefix + "_branch2c", pad=0
        )
        if cfg.MODEL.CUSTOM_BN_INIT:
            self.model.param_init_net.ConstantFill(
                [bn_blob + '_s'], bn_blob + '_s', value=cfg.MODEL.BN_INIT_GAMMA
            )
        sc_blob = self.add_shortcut(
            blob_in, dim_in, dim_out, stride, prefix=prefix + "_branch1"
        )
        if cfg.MODEL.ALLOW_INPLACE_SUM:
            sum_blob = self.model.net.Sum([bn_blob, sc_blob], bn_blob)
        else:
            sum_blob = self.model.net.Sum([bn_blob, sc_blob], prefix + "_sum")
        return self.model.Relu(sum_blob, sum_blob)

    def residual_layer(
        self, block_fn, blob_in, dim_in, dim_out, stride, num_blocks, prefix,
        dim_inner=None, group=None
    ):
        # prefix looks like: res2, res3, etc. Each res layer has num_blocks
        # stacked
        for idx in range(num_blocks):
            block_prefix = "{}_{}".format(prefix, idx)
            block_stride = 2 if (idx == 0 and stride == 2) else 1
            blob_in = block_fn(
                blob_in, dim_in, dim_out, block_stride, block_prefix, dim_inner,
                group
            )
            dim_in = dim_out
        return blob_in, dim_in
