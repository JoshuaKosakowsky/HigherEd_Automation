"""Locate a printed E-13B routing field even when ordinary OCR drops its symbols."""

from bisect import bisect_left, bisect_right
import cv2
import numpy as np

from .detection import Box


def transit_bands(image: np.ndarray) -> list[Box]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    parts = sorted(tuple(map(int, row)) for row in stats[1:] if row[3] >= 2 and row[2] >= 1)
    xs = [p[0] for p in parts]

    def nearby(left, right):
        return parts[bisect_left(xs, left):bisect_right(xs, right)]

    # A transit glyph has a short vertical stroke with two stacked squares to
    # its right. Compare dimensions to the stroke height, not to the paper.
    strokes = []
    for x, y, w, h, area in parts:
        if h < 5 or not (1.7*w <= h <= 4.8*w and area >= .74*w*h):
            continue
        dots = [(dx, dy+dh/2) for dx, dy, dw, dh, da in nearby(x+w, x+h*1.2)
                if .24*h <= dh <= .72*h and .65*dh <= dw <= 1.5*dh and da >= .70*dw*dh]
        center = y + h/2
        top = [(dx, cy) for dx, cy in dots if .27*h <= center-cy <= .85*h]
        bottom = [(dx, cy) for dx, cy in dots if .27*h <= cy-center <= .85*h]
        if any(abs(a-b) <= max(1, .17*h) for a, _ in top for b, _ in bottom):
            strokes.append((x, center, h))

    height, width = gray.shape
    bands = []
    for i, (x, y, h) in enumerate(strokes):
        for end, end_y, end_h in strokes[i+1:]:
            distance = end-x
            if distance > 23*h:
                break
            if distance < 11*h or abs(end_y-y) > .45*h or not .7*h <= end_h <= 1.35*h:
                continue
            # Two transit delimiters enclose nine digits on a ten-pitch span.
            pitch = distance / 10
            slope = (end_y-y) / distance
            aligned = [p for p in nearby(x-70*pitch, end+70*pitch)
                       if .2*h <= p[3] <= 2.1*h and p[2] <= 1.5*pitch
                       and abs((p[1]+p[3]/2) - (y+slope*(p[0]-x))) <= .85*h]
            digits = {round((px-x)/pitch) for px, _, _, ph, _ in aligned
                      if 1.1*h <= ph and abs((px-x)/pitch - round((px-x)/pitch)) < .45}
            if len(digits.intersection(range(1, 10))) < 7:
                continue
            # Extend the proposal across adjacent account/serial fields on
            # either side, including delimiters that text recognition missed.
            segment = []
            for part in aligned:
                if segment and part[0] - (segment[-1][0]+segment[-1][2]) > 4*pitch:
                    if segment[0][0] <= x and segment[-1][0] >= end:
                        break
                    segment.clear()
                segment.append(part)
            if segment and segment[0][0] <= x and segment[-1][0] >= end:
                bands.append(Box(segment[0][0]/width, min(p[1] for p in segment)/height,
                                 max(p[0]+p[2] for p in segment)/width,
                                 max(p[1]+p[3] for p in segment)/height))
                break
    return bands
