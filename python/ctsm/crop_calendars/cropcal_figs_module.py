import numpy as np
import xarray as xr
import cftime

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib import cm
    import matplotlib.collections as mplcol
except:
    pass

# Import the CTSM Python utilities
import utils


# Colormaps (maps)
cropcal_colors = {
    "seq_timeofyear": "twilight_shifted",
    "seq_other": "plasma",  # magma_r? CMRmap_r?
    "div_yieldirr": "BrBG",
    "div_timeofyear": "twilight_shifted",
    "div_other_nonnorm": "PuOr_r",
    "div_other_norm": "RdBu_r",
    "underlay": [0.75, 0.75, 0.75, 1],
    "underlay_lighter": [0.85, 0.85, 0.85, 1],
    "underlay_lightest": [0.92, 0.92, 0.92, 1],
}


# Cases (line and scatter plots)
def cropcal_colors_cases(casename):
    case_color_dict = {
        "clm default": [x / 255 for x in [92, 219, 219]],
        "prescribed calendars": [x / 255 for x in [250, 102, 240]],
        "prescribed maturity": [x / 255 for x in [128, 0, 0]],
        "prescribed sowing": [x / 255 for x in [133, 92, 255]],
    }
    case_color_dict["5.0 lu"] = case_color_dict["clm default"]
    case_color_dict["5.2 lu"] = case_color_dict["prescribed calendars"]

    case_color = None
    casename_for_colors = casename.lower().replace(" (0)", "").replace(" (1)", "")
    if casename_for_colors in case_color_dict:
        case_color = case_color_dict[casename_for_colors]
    return case_color


def make_map(
    ax,
    this_map,
    fontsize,
    bounds=None,
    cbar=None,
    cbar_labelpad=4.0,
    cbar_max=None,
    cbar_spacing="uniform",
    cmap=cropcal_colors["seq_other"],
    extend_bounds="both",
    extend_nonbounds="both",
    linewidth=1.0,
    lonlat_bin_width=None,
    show_cbar=False,
    subplot_label=None,
    this_title=None,
    ticklabels=None,
    ticklocations=None,
    underlay=None,
    underlay_color=None,
    units=None,
    vmax=None,
    vmin=None,
    vrange=None,
):
    if underlay is not None:
        if underlay_color is None:
            underlay_color = cropcal_colors["underlay"]
        underlay_cmap = mcolors.ListedColormap(np.array([underlay_color, [1, 1, 1, 1]]))
        ax.pcolormesh(underlay.lon.values, underlay.lat.values, underlay, cmap=underlay_cmap)

    if bounds is not None:
        norm = mcolors.BoundaryNorm(bounds, cmap.N, extend=extend_bounds)
        im = ax.pcolormesh(
            this_map.lon.values, this_map.lat.values, this_map, shading="auto", norm=norm, cmap=cmap
        )
    else:
        im = ax.pcolormesh(
            this_map.lon.values,
            this_map.lat.values,
            this_map,
            shading="auto",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )
        if vrange:
            im.set_clim(vrange[0], vrange[1])
    ax.set_extent([-180, 180, -63, 90], crs=ccrs.PlateCarree())

    if subplot_label is not None:
        plt.text(
            0, 0.95, f"({subplot_label})", transform=ax.transAxes, fontsize=fontsize["axislabels"]
        )

    # # Country borders
    # ax.add_feature(cfeature.BORDERS, linewidth=linewidth, edgecolor="white", alpha=0.5)
    # ax.add_feature(cfeature.BORDERS, linewidth=linewidth*0.6, alpha=0.3)

    # Coastlines
    ax.coastlines(linewidth=linewidth, color="white", alpha=0.5)
    ax.coastlines(linewidth=linewidth * 0.6, alpha=0.3)

    if this_title:
        ax.set_title(this_title, fontsize=fontsize["titles"])
    if show_cbar:
        if cbar:
            cbar.remove()

        if bounds is not None:
            cbar = plt.colorbar(
                cm.ScalarMappable(norm=norm, cmap=cmap),
                ax=ax,
                orientation="horizontal",
                fraction=0.1,
                pad=0.02,
                spacing=cbar_spacing,
            )
        else:
            cbar = plt.colorbar(
                im,
                ax=ax,
                orientation="horizontal",
                fraction=0.1,
                pad=0.02,
                extend=extend_nonbounds,
                spacing=cbar_spacing,
            )

        deal_with_ticklabels(cbar, cbar_max, ticklabels, ticklocations, units, im)
        cbar.set_label(
            label=units,
            fontsize=fontsize["axislabels"],
            verticalalignment="center",
            labelpad=cbar_labelpad,
        )
        cbar.ax.tick_params(labelsize=fontsize["ticklabels"])
        if units is not None and "month" in units.lower():
            cbar.ax.tick_params(length=0)

    if lonlat_bin_width:
        set_ticks(lonlat_bin_width, fontsize, "y")
        # set_ticks(lonlat_bin_width, fontsize, "x")
    else:
        # Need to do this for subplot row labels
        set_ticks(-1, fontsize, "y")
        plt.yticks([])
    for x in ax.spines:
        ax.spines[x].set_visible(False)

    if show_cbar:
        return im, cbar
    else:
        return im, None


def deal_with_ticklabels(cbar, cbar_max, ticklabels, ticklocations, units, im):
    if ticklocations is not None:
        cbar.set_ticks(ticklocations)
        if units is not None and units.lower() == "month":
            cbar.set_ticklabels(
                ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            )
            units == "Month"
        elif ticklabels is not None:
            cbar.set_ticklabels(ticklabels)
    if isinstance(im, mplcol.QuadMesh):
        clim_max = im.get_clim()[1]
    else:
        clim_max = im
    if cbar_max is not None and clim_max > cbar_max:
        if ticklabels is not None:
            raise RuntimeError(
                "How to handle this now that you are specifying ticklocations separate from ticklabels?"
            )
        ticks = cbar.get_ticks()
        if ticks[-2] > cbar_max:
            raise RuntimeError(
                f"Specified cbar_max is {cbar_max} but highest bin BEGINS at {ticks[-2]}"
            )
        ticklabels = ticks.copy()
        ticklabels[-1] = cbar_max
        for i, x in enumerate(ticklabels):
            if x == int(x):
                ticklabels[i] = str(int(x))
        cbar.set_ticks(
            ticks
        )  # Calling this before set_xticklabels() avoids "UserWarning: FixedFormatter should only be used together with FixedLocator" (https://stackoverflow.com/questions/63723514/userwarning-fixedformatter-should-only-be-used-together-with-fixedlocator)
        cbar.set_ticklabels(ticklabels)


def set_ticks(lonlat_bin_width, fontsize, x_or_y):
    if x_or_y == "x":
        ticks = np.arange(-180, 181, lonlat_bin_width)
    else:
        ticks = np.arange(-60, 91, lonlat_bin_width)

    ticklabels = [str(x) for x in ticks]
    for i, x in enumerate(ticks):
        if x % 2:
            ticklabels[i] = ""

    if x_or_y == "x":
        plt.xticks(ticks, labels=ticklabels, fontsize=fontsize["ticklabels"])
    else:
        plt.yticks(ticks, labels=ticklabels, fontsize=fontsize["ticklabels"])
