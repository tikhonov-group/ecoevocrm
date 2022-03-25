import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns

from matplotlib import rc
rc('font',**{'family':'sans-serif','sans-serif':['Helvetica']})


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def matrix_plot(mat, ax=None, cmap=None, vmin=None, vmax=None, center=None, cbar=None, cbar_kws=None, cbar_ax=None,
                square=True, robust=False, linewidths=0, linecolor='white', 
                xticklabels='auto', yticklabels='auto', mask=None, annot=None, fmt='.2g', annot_kws=None):
    
    if(cmap is None):
        if(np.any(mat < 0)):
            cmap   = 'RdBu'
            center = 0 if center == None else center
            vmin   = -1*np.max(np.abs(mat)) if vmin == None else vmin
            vmax   = np.max(np.abs(mat)) if vmax == None else vmax
        else:
            cmap = 'Greys'
            
    cbar = True if cbar is None and np.any((mat != 1) & (mat != 0)) else cbar

    with sns.axes_style('white'):
        ax = sns.heatmap(mat, ax=ax, cmap=cmap, vmin=vmin, vmax=vmax, center=center, 
                            robust=robust, annot=annot, fmt=fmt, annot_kws=annot_kws, 
                            linewidths=linewidths, linecolor=linecolor, 
                            cbar=cbar, cbar_kws=cbar_kws, cbar_ax=cbar_ax, square=square, 
                            xticklabels=xticklabels, yticklabels=yticklabels, mask=mask)


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def color_types_by_phylogeny(type_set, palette='hls', root_color='#AAAAAA', highlight_clades='all', apply_palette_depth=1, shuffle_palette=True, 
                             color_step_start=0.15, color_step_slope=0.01, color_step_min=0.01):

    # TODO: Make the range of random updates to child color based on phenotype or fitness difference between parent and child

    num_palette_types = 0
    lineage_ids = np.asarray(type_set.lineage_ids)
    for lineage_id in lineage_ids:
        if(lineage_id.count('.') == apply_palette_depth):
            num_palette_types += 1

    palette = sns.color_palette(palette, num_palette_types)
    if(shuffle_palette):
        np.random.shuffle(palette)
    
    type_colors = [root_color for i in range(type_set.num_types)]

    if(isinstance(highlight_clades, str) and highlight_clades == 'all'):
        highlight_clades = list(type_set.phylogeny.keys())
    
    def color_subtree(d, parent_color, depth, next_palette_color_idx):
        if(not isinstance(d, dict) or not d):
            return
        parent_color_rgb   = tuple(int(parent_color.strip('#')[i:i+2], 16)/255 for i in (0, 2, 4)) if ('#' in parent_color and len(parent_color)==7) else parent_color
        for lineage_id, descendants in d.items():
            type_idx       = np.argmax(lineage_ids == lineage_id)
            if(depth == apply_palette_depth):
                type_color = palette[next_palette_color_idx]
                next_palette_color_idx += 1
            elif(depth==0):
                type_color = parent_color_rgb
            elif(depth < apply_palette_depth):
                color_step_scale = max(color_step_start - color_step_slope*(depth-1), color_step_min)
                type_color = tuple([np.clip((parent_color_rgb[0] + np.random.uniform(low=-1*color_step_scale, high=color_step_scale)), 0, 1)]*3)
            else:
                color_step_scale = max(color_step_start - color_step_slope*(depth-1), color_step_min)
                type_color = tuple([np.clip((v + np.random.uniform(low=-1*color_step_scale, high=color_step_scale)), 0, 1) for v in parent_color_rgb])
            type_colors[type_idx] = type_color
            color_subtree(descendants, type_color, depth+1, next_palette_color_idx)
        
    color_subtree(type_set.phylogeny, parent_color=root_color, depth=0, next_palette_color_idx=0)

    if(not (isinstance(highlight_clades, str) and highlight_clades == 'all')):
        lineage_ids = np.asarray([lid+'.' for lid in lineage_ids])
        for i, color in enumerate(type_colors):
            if(not any(lineage_ids[i].startswith(str(highlight_id).strip('.')+'.') for highlight_id in highlight_clades)):
                type_colors[i] = [type_colors[i][0]]*3

    return type_colors


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def stacked_abundance_plot(system, ax=None, relative_abundance=False, t_downsample='default',
                            type_colors=None, palette='hls', root_color='#AAAAAA', highlight_clades='all', apply_palette_depth=1, shuffle_palette=True, 
                            color_step_start=0.15, color_step_slope=0.01, color_step_min=0.01,
                            linewidth=None, edgecolor=None):

    if(type_colors is None):
        type_colors = color_types_by_phylogeny(system.type_set, palette=palette, root_color=root_color, highlight_clades=highlight_clades, apply_palette_depth=apply_palette_depth, shuffle_palette=shuffle_palette, color_step_start=color_step_start, color_step_slope=color_step_slope, color_step_min=color_step_min)

    if(t_downsample == 'default'):
        t_downsample = max(int((len(system.t_series)//10000)+1), 1)
    elif(t_downsample is None):
        t_downsample = 1
    
    ax = plt.axes() if ax is None else ax

    if(relative_abundance):
        ax.stackplot(system.t_series[::t_downsample], np.flip((system.N_series/np.sum(system.N_series, axis=0))[:, ::t_downsample], axis=0), baseline='sym', colors=type_colors[::-1], linewidth=linewidth, edgecolor=edgecolor)
    else:
        ax.stackplot(system.t_series[::t_downsample], np.flip(system.N_series[:, ::t_downsample], axis=0), baseline='sym', colors=type_colors[::-1], linewidth=linewidth, edgecolor=edgecolor)

    return ax


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def Lstar_types_plot(system, ax=None, figsize=(7,5)):
    import ecoevocrm.coarse_graining as cg
    Lstar_types_data = cg.get_Lstar_types(system)

    ax = plt.axes() if ax is None else ax

    with sns.axes_style('white'):
        ax.plot(Lstar_types_data[0], Lstar_types_data[1])
    
        ax.set_xlim(xmin=0)
        ax.set_ylim(ymin=0)
        ax.set_xlabel('L$^*$')
        ax.set_ylabel('number of unique types')

        sns.despine()


