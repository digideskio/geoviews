import copy
import itertools

import param
import numpy as np
import shapely.geometry
from cartopy.crs import GOOGLE_MERCATOR

from holoviews import Store
from holoviews.core import util
from holoviews.core.options import Options
from holoviews.plotting.util import map_colors
from holoviews.plotting.bokeh.element import ElementPlot
from holoviews.plotting.bokeh.chart import PointPlot
from holoviews.plotting.bokeh.path import PolygonPlot, PathPlot
from holoviews.plotting.bokeh.raster import RasterPlot
from holoviews.plotting.bokeh.util import get_cmap

from ...element import (WMTS, Points, Polygons, Path, Shape, Image,
                        Image, Feature, is_geographic)
from ...operation import ProjectImage
from ...util import project_extents, geom_to_array

DEFAULT_PROJ = GOOGLE_MERCATOR

line_types = (shapely.geometry.MultiLineString, shapely.geometry.LineString)
poly_types = (shapely.geometry.MultiPolygon, shapely.geometry.Polygon)


class GeoPlot(ElementPlot):
    """
    Plotting baseclass for geographic plots with a cartopy projection.
    """

    show_grid = param.Boolean(default=False)

    def __init__(self, element, **params):
        super(GeoPlot, self).__init__(element, **params)
        self.geographic = is_geographic(self.hmap.last)

    def get_extents(self, element, ranges):
        """
        Subclasses the get_extents method using the GeoAxes
        set_extent method to project the extents to the
        Elements coordinate reference system.
        """
        extents = super(GeoPlot, self).get_extents(element, ranges)
        if not getattr(element, 'crs', None):
            return extents
        elif any(e is None or not np.isfinite(e) for e in extents):
            return (np.NaN,)*4
        return project_extents(extents, element.crs, DEFAULT_PROJ)


class TilePlot(GeoPlot):

    styl_opts = ['alpha', 'render_parents']
    
    def get_data(self, element, ranges=None, empty=False):
        return {}, {'tile_source': element.data}
    
    def _init_glyph(self, plot, mapping, properties):
        """
        Returns a Bokeh glyph object.
        """
        renderer = plot.add_tile(mapping['tile_source'])
        return renderer, renderer


class GeoPointPlot(GeoPlot, PointPlot):

    def get_data(self, *args, **kwargs):
        data, mapping = super(GeoPointPlot, self).get_data(*args, **kwargs)
        element = args[0]
        dims = element.dimensions(label=True)
        points = DEFAULT_PROJ.transform_points(element.crs, data[dims[0]],
                                               data[dims[1]])
        data[dims[0]] = points[:, 0]
        data[dims[1]] = points[:, 1]
        return data, mapping


class GeoRasterPlot(GeoPlot, RasterPlot):

    def get_data(self, element, ranges=None, empty=False):
        l, b, r, t = self.get_extents(element, ranges)
        if self.geographic:
            element = ProjectImage(element, projection=DEFAULT_PROJ)
        img = element.dimension_values(2, flat=False).T
        mapping = dict(image='image', x='x', y='y', dw='dw', dh='dh')
        if empty:
            data = dict(image=[], x=[], y=[], dw=[], dh=[])
        else:
            dh = t-b
            data = dict(image=[img], x=[l],
                        y=[b], dw=[r-l], dh=[dh])
        return (data, mapping)


class GeometryPlot(GeoPlot):
    """
    Geometry projects a geometry to the destination coordinate
    reference system before creating the glyph.
    """

    def get_data(self, element, ranges=None, empty=False):
        data, mapping = super(GeometryPlot, self).get_data(element, ranges, empty)
        if not self.geographic:
            return data, mapping
        geoms = DEFAULT_PROJ.project_geometry(element.geom(), element.crs)
        xs, ys = geom_to_array(geoms)
        data['xs'] = xs
        data['ys'] = ys
        return data, mapping


class GeoPolygonPlot(GeometryPlot, PolygonPlot):
    pass


class GeoPathPlot(GeometryPlot, PathPlot):
    pass


class GeoShapePlot(GeoPolygonPlot):

    def get_data(self, element, ranges=None, empty=False):
        geoms = element.geom()
        if getattr(element, 'crs', None):
            try:
                geoms = DEFAULT_PROJ.project_geometry(geoms, element.crs)
            except:
                empty = True
        xs, ys = ([], []) if empty else geom_to_array(geoms)
        data = dict(xs=xs, ys=ys)

        style = self.style[self.cyclic_index]
        cmap = style.get('palette', style.get('cmap', None))
        mapping = dict(self._mapping)
        dim = element.vdims[0].name if element.vdims else None
        if cmap and dim and element.level is not None:
            cmap = get_cmap(cmap)
            colors = map_colors(np.array([element.level]),
                                ranges[dim], cmap)
            mapping['color'] = 'color'
            data['color'] = [] if empty else list(colors)*len(element.data)
        if 'hover' in self.tools+self.default_tools:
            if dim:
                dim_name = util.dimension_sanitizer(dim)
                data[dim_name] = [element.level for _ in range(len(xs))]
            for k, v in self.overlay_dims.items():
                dim = util.dimension_sanitizer(k.name)
                data[dim] = [v for _ in range(len(xs))]
        return data, mapping


class FeaturePlot(GeoPolygonPlot):

    scale = param.ObjectSelector(default='110m',
                                 objects=['10m', '50m', '110m'],
                                 doc="The scale of the Feature in meters.")

    def get_data(self, element, ranges, empty=[]):
        feature = copy.copy(element.data)
        feature.scale = self.scale
        if not self.geographic:
            return data, mapping

        geoms = list(feature.geometries())
        if isinstance(geoms[0], line_types):
            self._plot_methods = dict(single='multi_line')
        else:
            self._plot_methods = dict(single='patches', batched='patches')
        geoms = [DEFAULT_PROJ.project_geometry(geom, element.crs)
                 for geom in geoms]
        arrays = [geom_to_array(geom) for geom in geoms]
        xs = [arr[0] for arr in arrays]
        ys = [arr[1] for arr in arrays]
        data = dict(xs=list(itertools.chain(*xs)),
                    ys=list(itertools.chain(*ys)))
        return data, dict(self._mapping)


Store.register({WMTS: TilePlot,
                Points: GeoPointPlot,
                Polygons: GeoPolygonPlot,
                Path: GeoPathPlot,
                Shape: GeoShapePlot,
                Image: GeoRasterPlot,
                Feature: FeaturePlot}, 'bokeh')

options = Store.options(backend='bokeh')

options.Feature = Options('style', line_color='black')