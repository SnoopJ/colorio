import matplotlib.pyplot as plt
import numpy as np

from ..cs import SrgbLinear


class Dataset:
    def plot(self):
        raise NotImplementedError("Derived classes must implement plot().")

    def show(self, *args):
        plt.figure()
        self.plot(*args)
        plt.show()
        plt.close()

    def savefig(self, filename, *args):
        plt.figure()
        self.plot(*args)
        plt.savefig(filename, transparent=True, bbox_inches="tight")
        plt.close()


class ColorDifferenceDataset(Dataset):
    def __init__(self, name, dist, xyz_pairs):
        self.name = name
        self.dist = np.asarray(dist)
        self.xyz_pairs = np.asarray(xyz_pairs)

    def plot(self, cs):
        coords = cs.from_xyz100(self.xyz_pairs.T).T

        # reorder the coords such that the lightness in the last (the z-)component
        coords = np.roll(coords, 2 - cs.k0, axis=0)
        labels = np.roll(cs.labels, 2 - cs.k0, axis=0)

        ax = plt.axes(projection="3d")
        for pair in coords:
            ax.plot(pair[:, 0], pair[:, 1], pair[:, 2], "-k")

        ax.set_xlabel(labels[0])
        ax.set_ylabel(labels[1])
        ax.set_zlabel(labels[2])
        ax.set_title(f"{self.name} dataset in {cs.name}")

    def stress(self, cs):
        cs_pairs = cs.from_xyz100(self.xyz_pairs.T).T
        cs_diff = cs_pairs[:, 1] - cs_pairs[:, 0]

        delta = np.sqrt(np.einsum("ij,ij->i", cs_diff, cs_diff))

        alpha = np.dot(self.dist, delta) / np.dot(self.dist, self.dist)
        diff = alpha * self.dist - delta
        return 100 * np.sqrt(np.dot(diff, diff) / np.dot(delta, delta))


def _compute_straight_line_stress(cs, wp, d):
    """Compute the TLS residuals for each of the arms."""
    # remove the row corresponding to lightness
    idx = [True, True, True]
    idx[cs.k0] = False
    wp_cs = cs.from_xyz100(wp)[idx]
    s2 = []
    for dd in d:
        vals = cs.from_xyz100(dd)[idx]
        # move values such that whitepoint is in the origin
        vals = (vals.T - wp_cs).T
        # could also be computed explicitly
        s_max, s_min = np.linalg.svd(vals, compute_uv=False)
        s2.append(s_min / s_max)
        # plt.plot(vals[0], vals[1], "x")
        # plt.gca().set_aspect("equal")
        # plt.show()
    return 100 * np.array(s2)


def _plot_hue_linearity_data(
    data_xyz100, wp_xyz100, colorspace, approximate_colors_in_srgb=False
):
    # k0 is the coordinate that corresponds to "lightness"
    k0 = colorspace.k0
    k1, k2 = [k for k in [0, 1, 2] if k != k0]

    wp = colorspace.from_xyz100(wp_xyz100)[[k1, k2]]
    srgb = SrgbLinear()
    for xyz in data_xyz100:
        d = colorspace.from_xyz100(xyz)[[k1, k2]]

        # get the eigenvector corresponding to the larger eigenvalue
        d_wp = (d.T - wp).T
        vals, vecs = np.linalg.eigh(d_wp @ d_wp.T)
        v = vecs[:, 0] if vals[0] > vals[1] else vecs[:, 1]

        if np.dot(v, np.average(d, axis=1)) < 0:
            v = -v

        length = np.sqrt(np.max(np.einsum("ij,ij->i", d.T - wp, d.T - wp)))
        end_point = wp + length * v
        plt.plot([wp[0], end_point[0]], [wp[1], end_point[1]], "-", color="0.5")

        for dd, rgb in zip(d.T, srgb.from_xyz100(xyz).T):
            if approximate_colors_in_srgb:
                is_legal_srgb = True
                rgb[rgb > 1] = 1
                rgb[rgb < 0] = 0
            else:
                is_legal_srgb = np.all(rgb >= 0) and np.all(rgb <= 1)
            col = srgb.to_rgb1(rgb) if is_legal_srgb else "white"
            ecol = srgb.to_rgb1(rgb) if is_legal_srgb else "black"
            plt.plot(dd[0], dd[1], "o", color=col, markeredgecolor=ecol)

    plt.xlabel(colorspace.labels[k1])
    plt.ylabel(colorspace.labels[k2])
    plt.axis("equal")

    # plt.grid()
    plt.grid(False)
    ax = plt.gca()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)


def _compute_ellipse_residual(cs, xyy100_centers, xyy100_points):
    distances = []
    for xyy100_center, xyy100_pts in zip(xyy100_centers, xyy100_points):
        # append Y
        cs_center = cs.from_xyz100(_xyy100_to_xyz100(xyy100_center))
        cs_ellips = cs.from_xyz100(_xyy100_to_xyz100(xyy100_pts))
        # compute distances to ellipse center
        diff = (cs_center - cs_ellips.T).T
        distances.append(np.sqrt(np.einsum("ij,ij->j", diff, diff)))

    distances = np.concatenate(distances)
    alpha = np.average(distances)
    return np.sqrt(np.sum((alpha - distances) ** 2) / np.sum(distances ** 2))


def _xyy100_to_xyz100(xyy):
    x, y, Y = xyy
    return np.array([Y / y * x, Y, Y / y * (1 - x - y)])


def _plot_ellipses(xyy100_centers, xyy100_points, cs, ellipse_scaling=1.0):
    from matplotlib.patches import Ellipse
    from scipy.optimize import leastsq

    for center, points in zip(xyy100_centers, xyy100_points):
        # cut off the irrelevant index
        cs_center = cs.from_xyz100(_xyy100_to_xyz100(center))
        cs_points = cs.from_xyz100(_xyy100_to_xyz100(points))

        # project out lightness component
        tcenter = np.delete(cs_center, cs.k0)
        tvals = np.delete(cs_points, cs.k0, axis=0)

        # Given these new transformed vals, find the ellipse that best fits those
        # points
        X = (tvals.T - tcenter).T

        def f_ellipse(a_b_theta):
            a, b, theta = a_b_theta
            sin_t = np.sin(theta)
            cos_t = np.cos(theta)
            return (
                +(a ** 2) * (X[0] * cos_t + X[1] * sin_t) ** 2
                + b ** 2 * (X[0] * sin_t - X[1] * cos_t) ** 2
                - 1.0
            )

        def jac(a_b_theta):
            a, b, theta = a_b_theta
            x0sin = X[0] * np.sin(theta)
            x0cos = X[0] * np.cos(theta)
            x1sin = X[1] * np.sin(theta)
            x1cos = X[1] * np.cos(theta)
            return np.array(
                [
                    +2 * a * (x0cos + x1sin) ** 2,
                    +2 * b * (x0sin - x1cos) ** 2,
                    +(a ** 2) * 2 * (x0cos + x1sin) * (-x0sin + x1cos)
                    + b ** 2 * 2 * (x0sin - x1cos) * (x0cos + x1sin),
                ]
            ).T

        # We need to use some optimization here to find the new ellipses which best
        # fit the modified data.
        (a, b, theta), _ = leastsq(f_ellipse, [1.0, 1.0, 0.0], Dfun=jac)

        # plot the scaled ellipse
        e = Ellipse(
            xy=tcenter,
            width=ellipse_scaling * 2 / a,
            height=ellipse_scaling * 2 / b,
            angle=theta / np.pi * 180,
            # label=label,
        )
        plt.gca().add_patch(e)
        e.set_alpha(0.5)
        e.set_facecolor("k")

        # plt.plot(*tcenter, "xk")
        # plt.plot(*tvals, "ok")
        # plt.show()

    plt.gca().set_aspect("equal")
    labels = cs.labels[: cs.k0] + cs.labels[cs.k0 + 1 :]
    plt.xlabel(labels[0])
    plt.ylabel(labels[1])

    # mpl doesn't update axis limits when adding artists,
    # <https://github.com/matplotlib/matplotlib/issues/19290>.
    # Handle it manually for now.
    tcenters = []
    for center, points in zip(xyy100_centers, xyy100_points):
        cs_center = cs.from_xyz100(_xyy100_to_xyz100(center))
        tcenters.append(np.delete(cs_center, cs.k0))
    tcenters = np.asarray(tcenters).T
    xmin = np.min(tcenters[0])
    xmax = np.max(tcenters[0])
    ymin = np.min(tcenters[1])
    ymax = np.max(tcenters[1])
    width = xmax - xmin
    height = ymax - ymin
    plt.xlim(xmin - 0.2 * width, xmax + 0.2 * width)
    plt.ylim(ymin - 0.2 * height, ymax + 0.2 * height)
