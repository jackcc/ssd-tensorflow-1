#-------------------------------------------------------------------------------
# Author: Lukasz Janyst <lukasz@jany.st>
# Date:   29.08.2017
#-------------------------------------------------------------------------------
# This file is part of SSD-TensorFlow.
#
# SSD-TensorFlow is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SSD-TensorFlow is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SSD-Tensorflow.  If not, see <http://www.gnu.org/licenses/>.
#-------------------------------------------------------------------------------

import numpy as np

from utils import Size, Point, Overlap, Score, prop2abs
from collections import namedtuple
from math import sqrt, log

#-------------------------------------------------------------------------------
# Define the flavors of SSD that we're going to use and it's various properties.
# It's done so that we don't have to build the whole network in memory in order
# to pre-process the datasets.
#-------------------------------------------------------------------------------
SSDPreset = namedtuple('SSDPreset', ['image_size', 'num_maps', 'map_sizes',
                                     'num_anchors'])

SSD_PRESETS = {
    'vgg300': SSDPreset(image_size = Size(300, 300),
                        num_maps   = 6,
                        map_sizes  = [Size(38, 38),
                                      Size(19, 19),
                                      Size(10, 10),
                                      Size( 5,  5),
                                      Size( 3,  3),
                                      Size( 1,  1)],
                        num_anchors = 11639),
    'vgg500': SSDPreset(image_size = Size(500, 500),
                        num_maps   = 6,
                        map_sizes  = [Size(63, 63),
                                      Size(32, 32),
                                      Size(16, 16),
                                      Size( 8,  8),
                                      Size( 6,  6),
                                      Size( 4,  4)],
                        num_anchors = 32174)

    }

#-------------------------------------------------------------------------------
# Minimum and maximum scales for default boxes
#-------------------------------------------------------------------------------
SCALE_MIN  = 0.2
SCALE_MAX  = 0.9
SCALE_DIFF = SCALE_MAX - SCALE_MIN

#-------------------------------------------------------------------------------
# Default box parameters both in terms proportional to image dimensions
#-------------------------------------------------------------------------------
Anchor = namedtuple('Anchor', ['center', 'size', 'x', 'y', 'scale', 'map'])

#-------------------------------------------------------------------------------
def get_preset_by_name(pname):
    if not pname in SSD_PRESETS:
        raise RuntimeError('No such preset: '+pname)
    return SSD_PRESETS[pname]

#-------------------------------------------------------------------------------
def get_anchors_for_preset(preset):
    """
    Compute the default (anchor) boxes for the given SSD preset
    """
    #---------------------------------------------------------------------------
    # Compute scales for each feature map
    #---------------------------------------------------------------------------
    scales = []
    for k in range(1, preset.num_maps+1):
        scale = SCALE_MIN + SCALE_DIFF/(preset.num_maps-1)*(k-1)
        scales.append(scale)

    #---------------------------------------------------------------------------
    # Compute the width and heights of the anchor boxes for every scale
    #---------------------------------------------------------------------------
    aspect_ratios = [1, 2, 3, 0.5, 1/3]
    aspect_ratios = list(map(lambda x: sqrt(x), aspect_ratios))

    box_sizes = {}
    for i in range(len(scales)):
        s = scales[i]
        box_sizes[s] = []
        for ratio in aspect_ratios:
            w = s * ratio
            h = s / ratio
            box_sizes[s].append((w, h))
        if i < len(scales)-1:
            s_prime = sqrt(scales[i]*scales[i+1])
            box_sizes[s].append((s_prime, s_prime))

    #---------------------------------------------------------------------------
    # Compute the actual boxes for every scale and feature map
    #---------------------------------------------------------------------------
    anchors = []
    for k in range(len(scales)):
        s  = scales[k]
        fk = preset.map_sizes[k][0]
        for i in range(fk):
            x = (i+0.5)/float(fk)
            for j in range(fk):
                y = (j+0.5)/float(fk)
                for size in box_sizes[s]:
                    box = Anchor(Point(x, y), Size(size[0], size[1]),
                                 j, i, s, k)
                    anchors.append(box)
    return anchors

#-------------------------------------------------------------------------------
def jaccard_overlap(params1, params2):
    xmin1, xmax1, ymin1, ymax1 = params1
    xmin2, xmax2, ymin2, ymax2 = params2

    if xmax2 <= xmin1: return 0
    if xmax1 <= xmin2: return 0
    if ymax2 <= ymin1: return 0
    if ymax1 <= ymin2: return 0

    xmin = max(xmin1, xmin2)
    xmax = min(xmax1, xmax2)
    ymin = max(ymin1, ymin2)
    ymax = min(ymax1, ymax2)

    w = xmax-xmin
    h = ymax-ymin
    intersection = float(w*h)

    w1 = xmax1-xmin1
    h1 = ymax1-ymin1
    w2 = xmax2-xmin2
    h2 = ymax2-ymin2

    union = float(w1*h1) + float(w2*h2) - intersection

    return intersection/union

#-------------------------------------------------------------------------------
def compute_overlap(box, anchors, threshold):
    imgsize = Size(1000, 1000)
    bparams = prop2abs(box.center, box.size, imgsize)
    best    = None
    good    = []
    for i in range(len(anchors)):
        anchor  = anchors[i]
        aparams = prop2abs(anchor.center, anchor.size, imgsize)
        jaccard = jaccard_overlap(bparams, aparams)
        if jaccard == 0:
            continue
        elif not best or best.score < jaccard:
            best = Score(i, jaccard)

        if jaccard > threshold:
            good.append(Score(i, jaccard))

    return Overlap(best, good)

#-------------------------------------------------------------------------------
def compute_location(box, anchor):
    arr = np.zeros((4))
    arr[0] = (box.center.x-anchor.center.x)/anchor.size.w
    arr[1] = (box.center.y-anchor.center.y)/anchor.size.h
    arr[2] = log(box.size.w/anchor.size.w)
    arr[3] = log(box.size.h/anchor.size.h)
    return arr