# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the PyMVPA package for the
#   copyright and license terms.
#
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Unit tests for PyMVPA surface searchlight voxel selection"""

import numpy as np
from numpy.testing.utils import assert_array_almost_equal

import nibabel as nb

import os
import tempfile

from mvpa2.testing import *
from mvpa2.testing.datasets import datasets

from mvpa2 import cfg
from mvpa2.base import externals
from mvpa2.datasets import Dataset
from mvpa2.measures.base import Measure
from mvpa2.datasets.mri import fmri_dataset

from mvpa2.support.nibabel import surf, surf_fs_asc
from mvpa2.misc.surfing import surf_voxel_selection, queryengine, volgeom, \
                                volsurf

from mvpa2.measures.searchlight import Searchlight
from mvpa2.misc.surfing.queryengine import SurfaceVerticesQueryEngine, \
                                            disc_surface_queryengine

from mvpa2.measures.base import Measure, \
        TransferMeasure, RepeatedMeasure, CrossValidation
from mvpa2.clfs.smlr import SMLR
from mvpa2.generators.partition import OddEvenPartitioner
from mvpa2.mappers.fx import mean_sample
from mvpa2.misc.io.base import SampleAttributes
from mvpa2.mappers.detrend import poly_detrend
from mvpa2.mappers.zscore import zscore
from mvpa2.misc.neighborhood import Sphere, IndexQueryEngine
from mvpa2.clfs.gnb import GNB

#from mvpa2.suite import *
#from mvpa2.datasets.mri import fmri_dataset


class SurfVoxelSelectionTests(unittest.TestCase):
    # runs voxel selection and searchlight (surface-based) on haxby 2001 
    # single plane data using a synthetic planar surface 

    # checks to see if results are identical for surface
    # and volume base searchlights (the former using Euclidian distance

    def test_voxel_selection(self):
        '''Define searchlight radius (in mm)
        
        Note that the current value is a float; if it were int, it would 
        specify the number of voxels in each searchlight'''
        radius = 10.


        '''Define input filenames'''
        epi_fn = os.path.join(pymvpa_dataroot, 'bold.nii.gz')
        maskfn = os.path.join(pymvpa_dataroot, 'mask.nii.gz')

        '''
        Use the EPI datafile to define a surface.
        The surface has as many nodes as there are voxels
        and is parallel to the volume 'slice'
        '''
        vg = volgeom.from_any(maskfn, mask_volume=True)

        aff = vg.affine
        nx, ny, nz = vg.shape[:3]

        '''Plane goes in x and y direction, so we take these vectors
        from the affine transformation matrix of the volume'''
        plane = surf.generate_plane(aff[:3, 3], aff[:3, 0], aff[:3, 1],
                                    nx, ny)



        '''
        Simulate pial and white matter as just above and below 
        the central plane
        '''
        normal_vec = aff[:3, 2]
        outer = plane + normal_vec
        inner = plane + -normal_vec

        '''
        Combine volume and surface information
        '''
        vs = volsurf.VolSurf(vg, outer, inner)

        '''
        Run voxel selection with specified radius (in mm), using
        Euclidian distance measure
        '''
        surf_voxsel = surf_voxel_selection.voxel_selection(vs, radius,
                                                    distance_metric='e')

        '''
        Load an apply a volume - metric mask, and get a new instance
        of voxel selection results.
        In this new instance, only voxels that survive the epi mask
        are kept
        '''
        #epi_mask = fmri_dataset(maskfn).samples[0]
        #voxsel_masked = voxsel.get_masked_instance(epi_mask)


        '''Define cross validation'''
        cv = CrossValidation(GNB(), OddEvenPartitioner(),
                                  errorfx=lambda p, t: np.mean(p == t))

        '''
        Surface analysis: define the query engine, cross validation, 
        and searchlight
        '''
        surf_qe = SurfaceVerticesQueryEngine(surf_voxsel)
        surf_sl = Searchlight(cv, queryengine=surf_qe, postproc=mean_sample())


        '''
        new (Sep 2012): also test 'simple' queryengine wrapper function
        '''

        surf_qe2 = disc_surface_queryengine(radius, maskfn, inner, outer,
                                            plane, volume_mask=True,
                                            distance_metric='euclidian')
        surf_sl2 = Searchlight(cv, queryengine=surf_qe2,
                               postproc=mean_sample())


        '''
        Same for the volume analysis
        '''
        element_sizes = tuple(map(abs, (aff[0, 0], aff[1, 1], aff[2, 2])))
        sph = Sphere(radius, element_sizes=element_sizes)
        kwa = {'voxel_indices': sph}

        vol_qe = IndexQueryEngine(**kwa)
        vol_sl = Searchlight(cv, queryengine=vol_qe, postproc=mean_sample())


        '''The following steps are similar to start_easy.py'''
        attr = SampleAttributes(os.path.join(pymvpa_dataroot,
                                'attributes_literal.txt'))

        mask = surf_voxsel.get_mask()

        dataset = fmri_dataset(samples=os.path.join(pymvpa_dataroot,
                                                    'bold.nii.gz'),
                                                    targets=attr.targets,
                                                    chunks=attr.chunks,
                                                    mask=mask)

        # do chunkswise linear detrending on dataset
        poly_detrend(dataset, polyord=1, chunks_attr='chunks')

        # zscore dataset relative to baseline ('rest') mean
        zscore(dataset, chunks_attr='chunks', param_est=('targets', ['rest']))

        # select class face and house for this demo analysis
        # would work with full datasets (just a little slower)
        dataset = dataset[np.array([l in ['face', 'house']
                                    for l in dataset.sa.targets],
                                    dtype='bool')]

        '''Apply searchlight to datasets'''
        surf_dset = surf_sl(dataset)
        surf_dset2 = surf_sl2(dataset)
        vol_dset = vol_sl(dataset)

        surf_data = surf_dset.samples
        surf_data2 = surf_dset2.samples
        vol_data = vol_dset.samples

        assert_array_equal(surf_data, surf_data2)
        assert_array_equal(surf_data, vol_data)

    def test_voxel_selection_alternative_calls(self):
        # Tests a multitude of different searchlight calls
        # that all should yield exactly the same results.
        #
        # Calls differ by whether the arguments are filenames
        # or data objects, whether values are specified explicityly
        # or set to the default implicitly (using None).
        # and by different calls to run the voxel selection.
        #
        # This method does not test for mask functionality.

        # define the volume
        vol_shape = (50, 50, 50, 3)
        vol_affine = np.identity(4)

        # four versions: array, nifti image, file name, fmri dataset
        volarr = np.ones(vol_shape)
        volimg = nb.Nifti1Image(volarr, vol_affine)
        _, volfn = tempfile.mkstemp('vol.nii', 'test')
        volimg.to_filename(volfn)
        volds = fmri_dataset(volfn)

        # make the surfaces
        sphere_density = 10

        # two versions: Surface and file name
        outer = surf.generate_sphere(sphere_density) * 25. + 15
        inner = surf.generate_sphere(sphere_density) * 20. + 15
        intermediate = inner * .5 + outer * .5
        nv = outer.nvertices

        _, outerfn = tempfile.mkstemp('outer.asc', 'test')
        _, innerfn = tempfile.mkstemp('inner.asc', 'test')
        _, intermediatefn = tempfile.mkstemp('intermediate.asc', 'test')

        for s, fn in zip([outer, inner, intermediate],
                         [outerfn, innerfn, intermediatefn]):
            surf.write(fn, s, overwrite=True)

        # searchlight radius (in mm)
        radius = 10.

        # dataset used to run searchlight on
        ds = fmri_dataset(volfn)

        # simple voxel counter (run for each searchlight position)
        m = _Voxel_Count_Measure()

        # number of voxels expected in each searchlight
        r_expected = np.array([[76, 20, 22, 22, 13, 2, 9, 7, 7, 16, 20,
                                35, 37, 29, 14, 20, 32, 32, 34, 34, 15, 5,
                                25, 34, 35, 34, 25, 5, 15, 34, 34, 35, 33,
                                20, 14, 29, 37, 35, 33, 30, 21, 21, 23, 16,
                                27, 36, 36, 34, 35, 45, 43, 45, 43, 43, 49,
                                51, 49, 48, 48, 55, 55, 55, 55, 55, 55, 55,
                                55, 55, 55]])

        # start a combinatorial explosion
        for intermediate_ in [intermediate, intermediatefn, None]:
            for center_nodes_ in [None, range(nv)]:
                for volume_ in [volimg, volfn, volds]:
                    for surf_src_ in ['filename', 'surf']:
                        if surf_src_ == 'filename':
                            s_i, s_m, s_o = inner, intermediate, outer
                        elif surf_src_ == 'surf':
                                s_i, s_m, s_o = innerfn, intermediatefn, outerfn

                        for volume_mask_ in [None, True, 0, 2]:
                            for call_method_ in ["qe", "rvs", "gam"]:
                                if call_method_ == "qe":
                                    # use the fancy query engine wrapper
                                    qe = disc_surface_queryengine(radius,
                                            volume_, s_i, s_o, s_m,
                                            source_surf_nodes=center_nodes_,
                                            volume_mask=volume_mask_)
                                    sl = Searchlight(m, queryengine=qe)
                                    r = sl(ds).samples

                                elif call_method_ == 'rvs':
                                    # use query-engine but build the 
                                    # ingredients by hand
                                    vg = volgeom.from_any(volume_,
                                                          volume_mask_)
                                    vs = volsurf.VolSurf(vg, s_i, s_o)
                                    sel = surf_voxel_selection.voxel_selection(
                                            vs, radius, source_surf=s_m,
                                            source_surf_nodes=center_nodes_)
                                    qe = SurfaceVerticesQueryEngine(sel)
                                    sl = Searchlight(m, queryengine=qe)
                                    r = sl(ds).samples

                                elif call_method_ == 'gam':
                                    # build everything from the ground up
                                    vg = volgeom.from_any(volume_,
                                                          volume_mask_)
                                    vs = volsurf.VolSurf(vg, s_i, s_o)
                                    sel = surf_voxel_selection.voxel_selection(
                                            vs, radius, source_surf=s_m,
                                            source_surf_nodes=center_nodes_)
                                    mp = sel

                                    ks = sel.keys()
                                    nk = len(ks)
                                    r = np.zeros((1, nk))
                                    for i, k in enumerate(ks):
                                        r[0, i] = len(mp[k])

                                # check if result is as expected
                                assert_array_equal(r_expected, r)

        # clean up
        all_fns = [volfn, outerfn, innerfn, intermediatefn]
        map(os.remove, all_fns)


class _Voxel_Count_Measure(Measure):
    # used to check voxel selection results
    is_trained = True
    def __init__(self, **kwargs):
        Measure.__init__(self, **kwargs)

    def _call(self, dset):
        return dset.nfeatures

def suite():
    """Create the suite"""
    return unittest.makeSuite(SurfVoxelSelectionTests)


if __name__ == '__main__':
    import runner