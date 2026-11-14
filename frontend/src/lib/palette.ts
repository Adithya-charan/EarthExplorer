// Okabe-Ito colour-blind-safe palette (yellow darkened for contrast on white). Series are also
// distinguished by dash pattern so colour is never the only cue.
export const SERIES_COLORS = [
  "#0072B2", // blue
  "#D55E00", // vermillion
  "#009E73", // bluish green
  "#CC79A7", // reddish purple
  "#E69F00", // orange
  "#56B4E9", // sky blue
  "#4D4D4D", // dark grey
  "#A39A00", // dark yellow
];

export const SERIES_DASHES = ["0", "7 3", "2 3", "9 3 2 3", "4 2", "1 3", "12 4", "6 2 1 2"];

export const COLORS = {
  observed: "#0F1B2D",
  ols: "#D55E00",
  sen: "#0072B2",
  deseasonalized: "#009E73",
  grid: "#E2E8F0",
  axis: "#5B6B80",
};

export const seriesColor = (i: number) => SERIES_COLORS[i % SERIES_COLORS.length];
export const seriesDash = (i: number) => SERIES_DASHES[i % SERIES_DASHES.length];
