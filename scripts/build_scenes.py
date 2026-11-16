#!/usr/bin/env python3
"""Build one .blend per CUT from shotlist.json.

Deterministic by construction: every moving thing is driven by keyframes, never by a particle
system, cloth, fluid or any other simulation. That is what lets a shard start at an arbitrary
absolute frame and still render the same pixels as a full-timeline render.

    blender -b -P scripts/build_scenes.py -- --shotlist shotlist.json --out scenes
"""
import argparse
import json
import math
import os
import random
import sys

import bpy
import bmesh
from mathutils import Vector

W, H, FPS = 720, 1280, 30
SAMPLES = 48


# ----------------------------------------------------------------------------- scene plumbing
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_render(S, E):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = SAMPLES
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    except Exception:
        pass
    sc.cycles.max_bounces = 4
    sc.cycles.transmission_bounces = 4
    sc.cycles.transparent_max_bounces = 8
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.render.resolution_x = W
    sc.render.resolution_y = H
    sc.render.resolution_percentage = 100
    sc.render.fps = FPS
    sc.render.use_motion_blur = True
    sc.render.motion_blur_shutter = 0.5
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.image_settings.compression = 60
    sc.frame_start = S
    sc.frame_end = E
    sc.frame_set(S)
    try:
        sc.view_settings.view_transform = 'AgX'
        try:
            sc.view_settings.look = 'AgX - Medium High Contrast'
        except Exception:
            pass
    except Exception:
        try:
            sc.view_settings.view_transform = 'Filmic'
        except Exception:
            pass
    add_glare()


def add_glare():
    """Bloom. Blender 4.x puts the compositor on scene.node_tree; 5.x on a node group."""
    sc = bpy.context.scene
    try:
        if hasattr(sc, 'compositing_node_group'):
            ng = bpy.data.node_groups.new('comp', 'CompositorNodeTree')
            ng.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
            sc.compositing_node_group = ng
            nt = ng
            sink = nt.nodes.new('NodeGroupOutput').inputs['Image']
        else:
            sc.use_nodes = True
            nt = sc.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            sink = nt.nodes.new('CompositorNodeComposite').inputs['Image']
        rl = nt.nodes.new('CompositorNodeRLayers')
        gl = nt.nodes.new('CompositorNodeGlare')
        for attr, val in (('glare_type', 'FOG_GLOW'), ('quality', 'MEDIUM'),
                          ('threshold', 2.0), ('mix', 0.0), ('size', 7)):
            try:
                setattr(gl, attr, val)
            except Exception:
                pass
        for sock_name, val in (('Type', 'Fog Glow'), ('Quality', 'Medium'),
                               ('Threshold', 2.0), ('Size', 0.5), ('Strength', 1.0)):
            try:                                   # Blender 5.x: these are node inputs
                gl.inputs[sock_name].default_value = val
            except Exception:
                pass
        nt.links.new(rl.outputs['Image'], gl.inputs['Image'])
        nt.links.new(gl.outputs['Image'], sink)
    except Exception as exc:                                    # bloom is optional, never fatal
        print(f'  glare skipped: {exc}')


def world_dark(color=(0.004, 0.006, 0.014)):
    w = bpy.data.worlds.new('world')
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (*color, 1.0)
    bg.inputs['Strength'].default_value = 1.0


# ----------------------------------------------------------------------------- materials
def _mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    return m, nt, nt.nodes['Material Output']


def emission_mat(name, color, strength):
    m, nt, out = _mat(name)
    sh = nt.nodes.new('ShaderNodeEmission')
    sh.name = 'Emission'
    sh.inputs['Color'].default_value = (*color, 1.0)
    sh.inputs['Strength'].default_value = strength
    nt.links.new(sh.outputs[0], out.inputs['Surface'])
    return m


def principled_mat(name, color, rough=0.5, metallic=0.0, alpha=1.0):
    m, nt, out = _mat(name)
    sh = nt.nodes.new('ShaderNodeBsdfPrincipled')
    sh.inputs['Base Color'].default_value = (*color, 1.0)
    sh.inputs['Roughness'].default_value = rough
    sh.inputs['Metallic'].default_value = metallic
    if alpha < 1.0:
        sh.inputs['Alpha'].default_value = alpha
        try:
            m.blend_method = 'BLEND'
        except Exception:
            pass
    nt.links.new(sh.outputs[0], out.inputs['Surface'])
    return m


def earth_mat(name='earth'):
    """Ocean blue below the ramp midpoint, land green above it."""
    m, nt, out = _mat(name)
    sh = nt.nodes.new('ShaderNodeBsdfPrincipled')
    tex = nt.nodes.new('ShaderNodeTexNoise')
    tex.inputs['Scale'].default_value = 2.4
    tex.inputs['Detail'].default_value = 8.0
    tex.inputs['Roughness'].default_value = 0.55
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.47
    ramp.color_ramp.elements[0].color = (0.010, 0.045, 0.22, 1)
    ramp.color_ramp.elements[1].position = 0.53
    ramp.color_ramp.elements[1].color = (0.06, 0.20, 0.09, 1)
    nt.links.new(tex.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], sh.inputs['Base Color'])
    sh.inputs['Roughness'].default_value = 0.62
    nt.links.new(sh.outputs[0], out.inputs['Surface'])
    return m


def rim_glow_mat(name, color, strength, blend=0.5):
    """Transparent face-on, glowing only at the very limb: an atmosphere."""
    m, nt, out = _mat(name)
    lw = nt.nodes.new('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = blend
    em = nt.nodes.new('ShaderNodeEmission')
    em.name = 'Emission'
    em.inputs['Color'].default_value = (*color, 1.0)
    em.inputs['Strength'].default_value = strength
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    mix = nt.nodes.new('ShaderNodeMixShader')
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.45
    ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].position = 0.93
    ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(lw.outputs['Facing'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], mix.inputs['Fac'])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    return m


# ----------------------------------------------------------------------------- geometry
def sphere(name, radius, loc=(0, 0, 0), mat=None, segs=32, rings=16):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius)
    except TypeError:                                            # Blender < 3.0
        bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, diameter=radius)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    if mat:
        ob.data.materials.append(mat)
    return ob


def box(name, size, loc=(0, 0, 0), mat=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.scale = size
    ob.location = loc
    if mat:
        ob.data.materials.append(mat)
    return ob


def torus(name, major, minor, loc=(0, 0, 0), mat=None):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor,
                                     major_segments=48, minor_segments=12, location=loc)
    ob = bpy.context.object
    ob.name = name
    if mat:
        ob.data.materials.append(mat)
    return ob


def curve(name, pts, bevel=0.012, mat=None):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = (p[0], p[1], p[2], 1.0)
    cu.bevel_depth = bevel
    cu.bevel_resolution = 2
    ob = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(ob)
    if mat:
        ob.data.materials.append(mat)
    return ob


def dipole_lines(parent, length, azimuths=8, ladders=(1.7, 2.3, 3.0, 3.8), mat=None,
                 bevel=0.014):
    """Classic dipole field lines: r = L * sin^2(theta), magnetic axis on Z."""
    for L in ladders:
        for a in range(azimuths):
            phi = 2 * math.pi * a / azimuths
            pts = []
            n = 26
            for i in range(n + 1):
                th = math.pi * (0.055 + 0.89 * i / n)
                r = L * length * (math.sin(th) ** 2)
                pts.append((r * math.sin(th) * math.cos(phi),
                            r * math.sin(th) * math.sin(phi),
                            r * math.cos(th)))
            ob = curve(f'fl_{L}_{a}', pts, bevel, mat)
            ob.parent = parent


def stars(n=140, radius=70, seed=7, size=(0.05, 0.15), mat=None):
    rnd = random.Random(seed)
    m = mat or emission_mat('star', (0.85, 0.92, 1.0), 6.0)
    for i in range(n):
        u = rnd.uniform(-1.0, 1.0)
        th = rnd.uniform(0, 2 * math.pi)
        s = math.sqrt(max(0.0, 1.0 - u * u))
        p = (radius * s * math.cos(th), radius * s * math.sin(th), radius * u)
        sphere(f'star{i}', rnd.uniform(*size), p, m, segs=8, rings=6)


# ----------------------------------------------------------------------------- camera / light
def aim(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def camera(loc, target, lens=55.0, fstop=2.0, focus=None):
    cd = bpy.data.cameras.new('cam')
    cd.lens = lens
    # Portrait frames: Blender fits the sensor to the LONG side, so a 36 mm sensor crops hard.
    # Widening it to 64.8 mm gives the framing these shot lists were written for.
    cd.sensor_width = 64.8
    cam = bpy.data.objects.new('cam', cd)
    bpy.context.collection.objects.link(cam)
    cam.location = Vector(loc)
    aim(cam, target)
    bpy.context.scene.camera = cam
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    cd.dof.focus_distance = focus if focus is not None else (Vector(target) - Vector(loc)).length
    return cam


def key_cam(cam, frame, loc, target):
    cam.location = Vector(loc)
    aim(cam, target)
    cam.keyframe_insert('location', frame=frame)
    cam.keyframe_insert('rotation_euler', frame=frame)


def area_light(loc, energy, size, color=(1, 0.95, 0.9), target=(0, 0, 0)):
    ld = bpy.data.lights.new('key', 'AREA')
    ld.energy = energy
    ld.size = size
    ld.color = color
    ob = bpy.data.objects.new('key', ld)
    bpy.context.collection.objects.link(ob)
    ob.location = Vector(loc)
    aim(ob, target)
    return ob


def point_light(loc, energy, color=(1, 0.5, 0.2), radius=0.4):
    ld = bpy.data.lights.new('pt', 'POINT')
    ld.energy = energy
    ld.color = color
    ld.shadow_soft_size = radius
    ob = bpy.data.objects.new('pt', ld)
    bpy.context.collection.objects.link(ob)
    ob.location = Vector(loc)
    return ob


# ----------------------------------------------------------------------------- animation helpers
def key_loc(ob, f, loc):
    ob.location = Vector(loc)
    ob.keyframe_insert('location', frame=f)


def key_rot(ob, f, rot):
    ob.rotation_euler = rot
    ob.keyframe_insert('rotation_euler', frame=f)


def key_scale(ob, f, s):
    ob.scale = s if hasattr(s, '__len__') else (s, s, s)
    ob.keyframe_insert('scale', frame=f)


def fcurves_of(action):
    """Blender 4.0 keeps fcurves on the action; 4.4+/5.x keep them in slot channelbags."""
    try:
        return list(action.fcurves)
    except Exception:
        pass
    out = []
    for layer in getattr(action, 'layers', []):
        for strip in getattr(layer, 'strips', []):
            for bag in getattr(strip, 'channelbags', []):
                out.extend(bag.fcurves)
    return out


def set_interp(ob, interp='BEZIER'):
    ad = getattr(ob, 'animation_data', None)
    if not ad or not ad.action:
        return
    for fc in fcurves_of(ad.action):
        for kp in fc.keyframe_points:
            kp.interpolation = interp
            if interp == 'BEZIER':
                kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'


def flicker(sock, S, E, base, amp, seed, steps=9):
    """A lamp or an emission never holds still."""
    rnd = random.Random(seed)
    for i in range(steps):
        f = S + (E - S) * i / (steps - 1)
        sock.default_value = max(0.05, base * (1.0 + rnd.uniform(-amp, amp)))
        sock.keyframe_insert('default_value', frame=f)


def place_camera(S, E, c):
    """c = dict(loc0, loc1, tgt, lens, fstop, focus) -> an eased one-move camera."""
    cam = camera(c['loc0'], c['tgt'], lens=c['lens'], fstop=c['fstop'], focus=c.get('focus'))
    key_cam(cam, S, c['loc0'], c['tgt'])
    key_cam(cam, E, c['loc1'], c.get('tgt1', c['tgt']))
    set_interp(cam)
    return cam


def foreground(cam, offset=(0.58, -0.92, -1.6), radius=0.55, mat=None):
    """A soft dark shape clipping one corner of the lens: depth is the signature.

    Parented to the camera in camera space, so it stays a corner blob whatever the framing.
    """
    m = mat or principled_mat('fg', (0.02, 0.025, 0.04), 0.9)
    ob = sphere('fg', radius, (0, 0, 0), m, 20, 10)
    ob.parent = cam
    ob.location = offset
    return ob


# ----------------------------------------------------------------------------- shots
def shot_hook(S, E, v):
    """01 — the Sun throws a storm at a small blue world."""
    world_dark()
    stars(120, 90, seed=3)
    sun = sphere('sun', 6.0, (0, 0, -46), emission_mat('sun', (1.0, 0.42, 0.06), 8.0), 48, 24)
    sphere('earth', 1.75, (0, 0, -8), earth_mat(), 48, 24)
    sphere('atmo', 1.95, (0, 0, -8), rim_glow_mat('atmo', (0.3, 0.6, 1.0), 1.5), 32, 16)

    pm = emission_mat('particle', (0.55, 0.85, 1.0), 4.0)
    rnd = random.Random(11 + v)
    for i in range(150):
        x = rnd.uniform(-3.6, 3.6)
        y = rnd.uniform(-3.6, 3.6)
        z0 = rnd.uniform(-44.0, -40.0)
        z1 = rnd.uniform(-14.0, -9.5)
        ob = sphere(f'p{i}', rnd.uniform(0.035, 0.08), (x, y, z0), pm, 8, 6)
        t0 = S + rnd.uniform(-0.6, 0.9) * (E - S)
        key_loc(ob, t0, (x, y, z0))
        key_loc(ob, t0 + 0.42 * (E - S), (x * 0.72, y * 0.72, z1))
        set_interp(ob, 'LINEAR')

    area_light((2.5, 3.0, -30), 4000, 14, (1.0, 0.55, 0.2), (0, 0, -8))
    area_light((5.0, 4.0, -1.0), 900, 7, (0.7, 0.85, 1.0), (0, 0, -8))   # fill from camera side
    flicker(sun.data.materials[0].node_tree.nodes['Emission'].inputs['Strength'],
            S, E, 8.0, 0.06, 1)

    cams = [
        dict(loc0=(0, 0, 9.0), loc1=(0, 0, 4.2), tgt=(0, 0, -8), lens=52, fstop=1.6,
             focus=17.0, fg=((1.55, -1.05, 7.1), 0.95)),
        dict(loc0=(2.7, -1.3, -3.0), loc1=(1.7, -0.8, -5.1), tgt=(0, 0, -8), lens=70, fstop=1.7,
             focus=4.6, fg=((1.7, -1.5, -5.9), 0.42)),
        dict(loc0=(7.0, -2.4, -16.0), loc1=(4.6, -1.6, -13.4), tgt=(-1.0, 0, -25), lens=42,
             fstop=2.0, focus=12.0, fg=((4.8, -2.2, -19.6), 0.8)),
    ]
    c = cams[v % len(cams)]
    cam = place_camera(S, E, c)
    foreground(cam)


def shot_setup(S, E, v):
    """02 — Earth alone, naked, and still untouched."""
    world_dark()
    stars(170, 90, seed=5)
    earth = sphere('earth', 2.0, (0, 0, 0), earth_mat(), 64, 32)
    atmo = sphere('atmo', 2.12, (0, 0, 0), rim_glow_mat('atmo', (0.25, 0.55, 1.0), 1.6), 48, 24)
    key_rot(earth, S, (0, 0, 0.0))
    key_rot(earth, E, (0.02, 0.0, 0.55))
    set_interp(earth, 'LINEAR')

    sun_light = area_light((-9, -6, 5), 500, 12, (1.0, 0.94, 0.86), (0, 0, 0))
    key_loc(sun_light, S, (-9, -6, 5))
    key_loc(sun_light, E, (-7.5, -6.5, 4.2))
    set_interp(sun_light)
    flicker(atmo.data.materials[0].node_tree.nodes['Emission'].inputs['Strength'],
            S, E, 1.6, 0.10, 2)

    cams = [
        dict(loc0=(0.25, 0, 9.0), loc1=(0.25, 0, 6.1), tgt=(0, 0, 0), lens=58, fstop=1.8,
             focus=9.0, fg=((1.45, -0.95, 7.3), 1.1)),
        dict(loc0=(-2.9, -2.9, 2.9), loc1=(-2.3, -2.3, 2.3), tgt=(0.35, 0.35, 1.35), lens=90,
             fstop=1.9, focus=3.6, fg=((-1.1, -1.1, 2.0), 0.42)),
    ]
    c = cams[v % len(cams)]
    cam = place_camera(S, E, c)
    foreground(cam)


def shot_value(S, E, v):
    """03 — X-ray: the spinning liquid iron core that makes the field."""
    world_dark((0.006, 0.004, 0.012))
    stars(90, 80, seed=9)
    sphere('shell', 2.0, (0, 0, 0),
           principled_mat('shell', (0.10, 0.30, 0.70), rough=0.2, alpha=0.11), 64, 32)
    core = sphere('core', 0.75, (0, 0, 0), emission_mat('core', (1.0, 0.34, 0.04), 3.2), 32, 16)
    swirl = torus('swirl', 1.05, 0.20, (0, 0, 0), emission_mat('swirl', (1.0, 0.45, 0.08), 3.5))
    key_rot(swirl, S, (0.42, 0.0, 0.0))
    key_rot(swirl, E, (0.42, 0.0, 2 * math.pi))
    set_interp(swirl, 'LINEAR')
    key_rot(core, S, (0, 0, 0))
    key_rot(core, E, (0, 0, -1.6))
    set_interp(core, 'LINEAR')

    ring = bpy.data.objects.new('sparks', None)
    bpy.context.collection.objects.link(ring)
    spark_mat = emission_mat('spark', (1.0, 0.65, 0.15), 6.0)
    rnd = random.Random(4)
    for i in range(54):
        a = rnd.uniform(0, 2 * math.pi)
        r = rnd.uniform(0.7, 1.55)
        ob = sphere(f'sp{i}', rnd.uniform(0.02, 0.05),
                    (r * math.cos(a), r * math.sin(a), rnd.uniform(-0.35, 0.35)), spark_mat, 8, 6)
        ob.parent = ring
    key_rot(ring, S, (0, 0, 0))
    key_rot(ring, E, (0, 0, 3.4))
    set_interp(ring, 'LINEAR')

    pt = point_light((0, 0, 0), 150, (1.0, 0.42, 0.12), 0.9)
    rnd_l = random.Random(55)
    for i in range(9):                                    # the core light breathes
        f = S + (E - S) * i / 8
        pt.data.energy = 150 * (1.0 + rnd_l.uniform(-0.12, 0.12))
        pt.data.keyframe_insert('energy', frame=f)
    set_interp(pt)

    cams = [
        dict(loc0=(-1.75, -7.4, 1.0), loc1=(1.75, -7.4, 0.65), tgt=(0, 0, 0), lens=62, fstop=1.9,
             focus=7.6, fg=((1.9, -3.4, 1.7), 0.9)),
        dict(loc0=(0, -7.2, 1.5), loc1=(0, -5.8, 1.2), tgt=(0, 0, 0), lens=70, fstop=1.8,
             focus=6.6),
        dict(loc0=(0.6, -1.4, 6.4), loc1=(0.4, -1.0, 4.9), tgt=(0, 0, 0), lens=50, fstop=2.0,
             focus=5.2, fg=((1.2, -1.0, 5.6), 0.8)),
    ]
    c = cams[v % len(cams)]
    cam = place_camera(S, E, c)
    foreground(cam)


def shot_proof(S, E, v):
    """04 — a compass needle proves the field is real."""
    world_dark((0.008, 0.006, 0.012))
    disc = bpy.data.objects.new('disc', None)
    bpy.context.collection.objects.link(disc)
    d = box('dial', (4.4, 4.4, 0.18), (0, 0, 0),
            principled_mat('dial', (0.20, 0.21, 0.24), 0.45, 0.4))
    d.parent = disc
    n = box('needle', (0.13, 3.0, 0.09), (0, 0, 0.17),
            emission_mat('needle', (1.0, 0.18, 0.12), 3.0))
    n.parent = disc
    p = sphere('pivot', 0.17, (0, 0, 0.2),
               principled_mat('pivot', (0.7, 0.7, 0.75), 0.2, 1.0), 20, 10)
    p.parent = disc
    key_rot(disc, S, (0, 0, -0.62))
    key_rot(disc, S + 0.55 * (E - S), (0, 0, 0.19))
    key_rot(disc, S + 0.75 * (E - S), (0, 0, 0.10))
    key_rot(disc, E, (0, 0, 0.11))
    set_interp(disc)

    fl_mat = emission_mat("fl", (0.30, 0.85, 1.0), 3.5)
    fl = bpy.data.objects.new('fieldlines', None)
    bpy.context.collection.objects.link(fl)
    for k, z in enumerate((0.35, 1.1, 1.95)):
        pts = [(-5.5 + 11.0 * i / 40, 0.0, z - 0.045 * (-5.5 + 11.0 * i / 40) ** 2)
               for i in range(41)]
        ob = curve(f'fl{k}', pts, 0.012, fl_mat)
        ob.parent = fl
    key_rot(fl, S, (0, 0, -0.05))
    key_rot(fl, E, (0, 0, 0.05))
    set_interp(fl)
    flicker(fl_mat.node_tree.nodes['Emission'].inputs['Strength'], S, E, 2.5, 0.18, 6)

    area_light((0, -5, 6), 600, 8, (0.6, 0.8, 1.0), (0, 0, 0))
    area_light((2.0, -4.0, 2.0), 300, 5, (1.0, 0.9, 0.85), (0, 0, 0.5))
    c = dict(loc0=(0, -6.6, 3.4), loc1=(0, -5.1, 2.7), tgt=(0, 0, 0.6), lens=68, fstop=1.7,
             focus=6.8, fg=((1.5, -2.6, 2.3), 0.75))
    cam = place_camera(S, E, c)
    foreground(cam)


def shot_escalation(S, E, v):
    """05 — the storm arrives; the field is squashed on the Sun side."""
    world_dark()
    stars(110, 90, seed=13)
    sphere('earth', 1.5, (0, 0, 0), earth_mat(), 48, 24)
    sphere('atmo', 1.62, (0, 0, 0), rim_glow_mat('atmo', (0.3, 0.6, 1.0), 1.6), 40, 20)
    sphere('sun', 4.2, (-30, 0, 0), emission_mat('sun', (1.0, 0.45, 0.08), 7.0), 40, 20)

    field = bpy.data.objects.new('field', None)
    bpy.context.collection.objects.link(field)
    # tilted 20 degrees, and turned 22 degrees off the camera axis so no loop is edge-on
    field.rotation_euler = (math.radians(20), 0, math.radians(22))
    fl_mat = emission_mat('fl', (0.35, 0.85, 1.0), 1.8)
    dipole_lines(field, 1.5, azimuths=8, ladders=(1.8, 2.4, 3.1, 3.9), mat=fl_mat, bevel=0.011)
    key_scale(field, S, (1.0, 1.0, 1.0))
    key_scale(field, S + 0.35 * (E - S), (1.0, 1.0, 1.0))
    key_scale(field, E, (0.60, 1.0, 1.0))
    set_interp(field)
    flicker(fl_mat.node_tree.nodes['Emission'].inputs['Strength'], S, E, 1.8, 0.16, 8)

    pm = emission_mat('particle', (0.5, 0.8, 1.0), 4.0)
    rnd = random.Random(21 + v)
    for i in range(170):
        y = rnd.uniform(-3.2, 3.2)
        z = rnd.uniform(-3.2, 3.2)
        x0 = rnd.uniform(-26.0, -20.0)
        x1 = rnd.uniform(-3.0, -1.8)
        ob = sphere(f'p{i}', rnd.uniform(0.03, 0.07), (x0, y, z), pm, 8, 6)
        t0 = S + rnd.uniform(-0.5, 0.95) * (E - S)
        key_loc(ob, t0, (x0, y, z))
        key_loc(ob, t0 + 0.4 * (E - S), (x1, y * 0.55, z * 0.55))
        set_interp(ob, 'LINEAR')

    cams = [
        dict(loc0=(0, -9.4, 1.3), loc1=(0, -7.4, 1.0), tgt=(0, 0, 0), lens=45, fstop=2.2,
             focus=9.5, fg=((1.2, -4.2, 1.9), 1.0)),
        dict(loc0=(-6.2, -4.0, 1.1), loc1=(-4.9, -3.1, 0.9), tgt=(-1.4, 0, 0), lens=72,
             fstop=1.9, focus=5.0, fg=((-3.0, -2.4, 1.2), 0.45)),
    ]
    c = cams[v % len(cams)]
    cam = place_camera(S, E, c)
    foreground(cam)


def shot_twist(S, E, v):
    """06 — the leak: particles funnelled to the poles, aurora, Mars as the warning."""
    world_dark((0.004, 0.005, 0.016))
    stars(200, 120, seed=17)
    sphere('ground', 300.0, (0, 0, -300),
           principled_mat('ground', (0.05, 0.09, 0.12), 0.8), 128, 64)

    curtain = bpy.data.objects.new('curtain', None)
    bpy.context.collection.objects.link(curtain)
    gmat = emission_mat('aurora_g', (0.12, 1.0, 0.45), 2.5)
    pmat = emission_mat('aurora_p', (1.0, 0.25, 0.6), 2.0)
    rnd = random.Random(31)
    for i in range(44):
        x0 = -26 + 52 * i / 43 + rnd.uniform(-1.0, 1.0)
        y0 = rnd.uniform(20, 30)
        h = rnd.uniform(7, 13)
        pts = [(x0 + 1.6 * math.sin(2.2 * (j / 12) + i), y0 + 0.5 * (j / 12),
                12.0 * (j / 12) * (h / 12.0) + 0.4) for j in range(13)]
        ob = curve(f'au{i}', pts, 0.11, gmat)
        ob.parent = curtain
    for i in range(18):
        x0 = -20 + 40 * i / 17 + rnd.uniform(-1.0, 1.0)
        y0 = rnd.uniform(24, 34)
        h = rnd.uniform(12, 17)
        pts = [(x0 + 2.4 * math.sin(1.7 * (j / 9)), y0 + 0.4 * (j / 9), h * (j / 9) + 1.2)
               for j in range(10)]
        ob = curve(f'ap{i}', pts, 0.10, pmat)
        ob.parent = curtain
    key_rot(curtain, S, (0, 0, -0.03))
    key_rot(curtain, E, (0, 0, 0.03))
    set_interp(curtain)
    flicker(gmat.node_tree.nodes['Emission'].inputs['Strength'], S, E, 2.5, 0.35, 12, steps=13)
    flicker(pmat.node_tree.nodes['Emission'].inputs['Strength'], S, E, 2.0, 0.30, 14, steps=11)

    pm = emission_mat('rain', (0.6, 0.95, 1.0), 5.0)
    for i in range(22):
        x0 = rnd.uniform(-7, 7)
        ob = sphere(f'r{i}', 0.055, (x0, 14.0, 14.0), pm, 8, 6)
        for j in range(5):
            t = j / 4
            key_loc(ob, S + t * (E - S),
                    (x0 * (1 - 0.75 * t) + 1.4 * math.sin(3.4 * t), 14.0 + 6.0 * t,
                     14.0 * (1 - t) + 0.6))
        set_interp(ob, 'LINEAR')

    area_light((0, 12, 6), 150, 20, (0.4, 1.0, 0.6), (0, 20, 6))

    cams = [
        dict(loc0=(0, -6.5, 2.2), loc1=(0, -3.6, 4.1), tgt=(0, 20, 5.5), tgt1=(0, 20, 9.0),
             lens=42, fstop=2.0, focus=26.0, fg=((2.0, -2.9, 0.3), 1.4)),
        dict(loc0=(0, 2.0, 1.2), loc1=(0, 4.6, 2.9), tgt=(0, 24, 9.0), tgt1=(0, 24, 11.5),
             lens=35, fstop=2.4, focus=24.0, fg=((1.1, 1.4, 1.0), 0.7)),
        dict(loc0=(3.2, -2.2, 3.6), loc1=(2.3, -1.5, 2.9), tgt=(0, 14, 9.0), lens=58, fstop=1.8,
             focus=11.0, fg=((1.9, -0.7, 3.3), 0.55)),
    ]
    c = cams[v % len(cams)]
    cam = place_camera(S, E, c)
    foreground(cam)


def shot_resolution(S, E, v):
    """07 — pull back: the shield is the whole world's atmosphere."""
    world_dark()
    stars(200, 100, seed=23)
    sphere('earth', 1.6, (0, 0, 0), earth_mat(), 64, 32)
    sphere('atmo', 1.74, (0, 0, 0), rim_glow_mat('atmo', (0.3, 0.62, 1.0), 1.7), 48, 24)
    sphere('sun', 3.6, (-17, -4, -9), emission_mat('sun', (1.0, 0.5, 0.1), 7.0), 40, 20)

    field = bpy.data.objects.new('field', None)
    bpy.context.collection.objects.link(field)
    TILT = (math.radians(20), 0, math.radians(18))
    fl_mat = emission_mat('fl', (0.35, 0.85, 1.0), 1.8)
    dipole_lines(field, 1.6, azimuths=10, ladders=(1.8, 2.5, 3.2, 4.1), mat=fl_mat, bevel=0.011)
    key_rot(field, S, TILT)
    key_rot(field, E, (TILT[0], TILT[1], TILT[2] + 0.42))
    set_interp(field, 'LINEAR')
    flicker(fl_mat.node_tree.nodes['Emission'].inputs['Strength'], S, E, 1.8, 0.12, 18)

    pm = emission_mat('particle', (0.5, 0.8, 1.0), 4.0)
    rnd = random.Random(41)
    for i in range(110):
        y = rnd.uniform(-4, 4)
        z = rnd.uniform(-4, 4)
        x0 = rnd.uniform(-24, -18)
        ob = sphere(f'p{i}', rnd.uniform(0.03, 0.06), (x0, y, z), pm, 8, 6)
        t0 = S + rnd.uniform(-0.5, 0.9) * (E - S)
        key_loc(ob, t0, (x0, y, z))
        key_loc(ob, t0 + 0.45 * (E - S), (rnd.uniform(-6, -4), y * 0.6, z * 0.6))
        set_interp(ob, 'LINEAR')

    cams = [
        dict(loc0=(0.0, -3.2, 7.4), loc1=(0.0, -3.2, 15.5), tgt=(0, 0, 0), lens=50, fstop=2.0,
             focus=8.0),
        dict(loc0=(1.4, -2.6, 16.5), loc1=(0.9, -2.2, 12.8), tgt=(0, 0, 0), lens=45, fstop=2.1,
             focus=13.0),
    ]
    c = cams[v % len(cams)]
    cam = place_camera(S, E, c)
    foreground(cam)


BUILDERS = {
    '01-hook': shot_hook,
    '02-setup': shot_setup,
    '03-value': shot_value,
    '04-proof': shot_proof,
    '05-escalation': shot_escalation,
    '06-twist': shot_twist,
    '07-resolution': shot_resolution,
}


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument('--shotlist', default='shotlist.json')
    ap.add_argument('--out', default='scenes')
    args = ap.parse_args(argv)

    shotlist = json.load(open(args.shotlist, encoding='utf-8'))
    os.makedirs(args.out, exist_ok=True)
    for shot in shotlist['shots']:
        sid = shot['id']
        beat = shot.get('beat') or sid
        variant = int(shot.get('variant', 0))
        build = BUILDERS.get(beat)
        if build is None:
            sys.exit(f'no builder for cut {sid} (beat {beat})')
        reset()
        setup_render(shot['start'], shot['end'])
        build(shot['start'], shot['end'], variant)
        path = os.path.join(args.out, f'{sid}.blend')
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(path))
        print(f'built {path}  frames {shot["start"]}..{shot["end"]}')


if __name__ == '__main__':
    main()
