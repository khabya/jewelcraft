# ##### BEGIN GPL LICENSE BLOCK #####
#
#  JewelCraft jewelry design toolkit for Blender.
#  Copyright (C) 2015-2020  Mikhail Rachinskiy
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####


import operator
from math import pi

from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d
import bgl
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from ..lib import unit


def gamma_correction(color):
    return [x ** 2.2 for x in color]  # NOTE T74139


def loc_3d_to_2d(region, region_3d, loc, ratio_w, ratio_h):
    x, y = location_3d_to_region_2d(region, region_3d, loc)
    return x * ratio_w, y * ratio_h


def offscreen_refresh(self, context):
    if self.offscreen is not None:
        self.offscreen.free()

    width = self.region.width
    height = self.region.height
    self.offscreen = gpu.types.GPUOffScreen(width, height)

    mat_offscreen = Matrix()
    mat_offscreen[0][0] = 2 / width
    mat_offscreen[0][3] = -1
    mat_offscreen[1][1] = 2 / height
    mat_offscreen[1][3] = -1

    with self.offscreen.bind():
        bgl.glClearColor(0.0, 0.0, 0.0, 0.0)
        bgl.glClear(bgl.GL_COLOR_BUFFER_BIT)

        with gpu.matrix.push_pop():
            gpu.matrix.load_matrix(mat_offscreen)
            gpu.matrix.load_projection_matrix(Matrix())

            draw_gems(self, context, gamma_corr=True)


def draw_gems(self, context, ratio_w=1, ratio_h=1, gamma_corr=False):

    if gamma_corr:
        _c = gamma_correction
    else:
        _c = lambda x: x

    view_normal = self.region_3d.view_rotation @ Vector((0.0, 0.0, 1.0))

    if self.region_3d.is_perspective:
        angle_thold = pi / 1.8
        view_loc = self.region_3d.view_matrix.inverted().translation
    else:
        angle_thold = pi / 2.0
        center_xy = (self.region.width / 2.0, self.region.height / 2.0)
        view_loc = region_2d_to_origin_3d(self.region, self.region_3d, center_xy)

    from_scene_scale = unit.Scale(context).from_scene
    depsgraph = context.evaluated_depsgraph_get()
    gems = []
    app = gems.append

    for dup in depsgraph.object_instances:

        if dup.is_instance:
            ob = dup.instance_object.original
        else:
            ob = dup.object.original

        if "gem" not in ob or (self.use_select and not ob.select_get()):
            continue

        ob_stone = ob["gem"]["stone"]
        ob_cut = ob["gem"]["cut"]
        ob_size = tuple(round(x, 2) for x in from_scene_scale(ob.dimensions, batch=True))

        size_fmt, color = self.view_data.get((ob_stone, ob_cut, ob_size), (None, None))

        if color is None:
            continue

        mat = dup.matrix_world.copy()
        dist_from_view = (mat.translation - view_loc).length
        app((dist_from_view, ob, mat, size_fmt, color))

    shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
    fontid = 0
    blf.size(fontid, self.prefs.view_font_size_gem_size, 72)
    blf.color(fontid, 0.0, 0.0, 0.0, 1.0)

    gems.sort(key=operator.itemgetter(0), reverse=True)

    for _, ob, mat, size_fmt, color in gems:

        # Shape
        # -----------------------------

        ob_eval = ob.evaluated_get(depsgraph)
        me = ob_eval.to_mesh()
        me.transform(mat)
        verts = me.vertices

        shader.bind()
        shader.uniform_float("color", _c(color))

        for poly in me.polygons:
            if view_normal.angle(poly.normal) < angle_thold:
                cos = [
                    loc_3d_to_2d(self.region, self.region_3d, verts[v].co, ratio_w, ratio_h)
                    for v in poly.vertices
                ]
                batch = batch_for_shader(shader, "TRI_FAN", {"pos": cos})
                batch.draw(shader)

        ob_eval.to_mesh_clear()

        # Size
        # -----------------------------

        loc_x, loc_y = loc_3d_to_2d(self.region, self.region_3d, mat.translation, ratio_w, ratio_h)
        dim_x, dim_y = blf.dimensions(fontid, size_fmt)

        blf.position(fontid, loc_x - dim_x / 2, loc_y - dim_y / 2, 0.0)
        blf.draw(fontid, size_fmt)
