/**
 * Squarified treemap layout (Bruls/Huijsen/van Wijk 2000).
 *
 * Returns rectangles whose areas are proportional to item weights and whose
 * aspect ratios are as close to 1:1 as possible. Used to render the S&P 500
 * heatmap in TradingView style — mega-caps get big squares, mid-caps small ones.
 */

export type TreemapInput<T> = {
  id: string;
  value: number;      // weight (e.g. market cap)
  data: T;
};

export type TreemapRect = { x: number; y: number; w: number; h: number };

export type TreemapResult<T> = {
  item: TreemapInput<T>;
  rect: TreemapRect;
};

export function squarify<T>(items: TreemapInput<T>[], box: TreemapRect): TreemapResult<T>[] {
  const cleaned = items.filter((i) => i.value > 0);
  if (cleaned.length === 0) return [];

  const totalValue = cleaned.reduce((s, i) => s + i.value, 0);
  if (totalValue <= 0) return [];

  const totalArea = box.w * box.h;
  const scale = totalArea / totalValue;
  const scaled = cleaned
    .slice()
    .sort((a, b) => b.value - a.value)
    .map((i) => ({ ...i, value: i.value * scale }));

  return layout(scaled, box);
}

type Scaled<T> = TreemapInput<T> & { value: number };

function layout<T>(items: Scaled<T>[], box: TreemapRect): TreemapResult<T>[] {
  if (items.length === 0) return [];
  if (items.length === 1) {
    return [{ item: items[0], rect: box }];
  }

  const shortSide = Math.min(box.w, box.h);
  const row: Scaled<T>[] = [];
  let bestWorst = Infinity;
  let i = 0;

  while (i < items.length) {
    const candidate = [...row, items[i]];
    const worst = worstAspect(candidate, shortSide);
    if (row.length > 0 && worst > bestWorst) break;
    row.push(items[i]);
    bestWorst = worst;
    i++;
  }

  const result: TreemapResult<T>[] = [];
  const rowSum = row.reduce((s, it) => s + it.value, 0);
  const rest = items.slice(row.length);

  if (box.w >= box.h) {
    const rowWidth = rowSum / box.h;
    let y = box.y;
    for (const it of row) {
      const h = it.value / rowWidth;
      result.push({ item: it, rect: { x: box.x, y, w: rowWidth, h } });
      y += h;
    }
    result.push(
      ...layout(rest, { x: box.x + rowWidth, y: box.y, w: box.w - rowWidth, h: box.h }),
    );
  } else {
    const rowHeight = rowSum / box.w;
    let x = box.x;
    for (const it of row) {
      const w = it.value / rowHeight;
      result.push({ item: it, rect: { x, y: box.y, w, h: rowHeight } });
      x += w;
    }
    result.push(
      ...layout(rest, { x: box.x, y: box.y + rowHeight, w: box.w, h: box.h - rowHeight }),
    );
  }

  return result;
}

function worstAspect<T>(row: Scaled<T>[], shortSide: number): number {
  const sum = row.reduce((s, it) => s + it.value, 0);
  if (sum <= 0) return Infinity;
  let max = -Infinity;
  let min = Infinity;
  for (const it of row) {
    if (it.value > max) max = it.value;
    if (it.value < min) min = it.value;
  }
  const s2 = sum * sum;
  const side2 = shortSide * shortSide;
  return Math.max((side2 * max) / s2, s2 / (side2 * min));
}
