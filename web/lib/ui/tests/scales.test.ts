import assert from "node:assert/strict";
import { test } from "node:test";
import { areaPath, bandPath, extent, linearScale, linePath, niceDomain, niceTicks, rangeBarDomain } from "../scales.ts";
import { sortBy } from "../sort.ts";

test("scales and ticks", () => {
  const y = linearScale([0, 10], [100, 0]);
  assert.equal(y(5), 50);
  assert.equal(linearScale([3, 3], [0, 10])(3), 5);
  assert.deepEqual(extent([1, null, 3, Number.NaN]), [1, 3]);
  assert.equal(extent([null]), null);
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(niceTicks(-9876, 1016, 4), [-5000, 0]);
  assert.deepEqual(niceDomain(-9876, 1016, 4), [-10000, 5000]);
  assert.deepEqual(niceTicks(-10000, 5000, 4), [-10000, -5000, 0, 5000]);
  assert.deepEqual(niceTicks(2, 2), [2]);
});

test("paths", () => {
  assert.equal(linePath([{ x: 0, y: 1 }, null, { x: 2, y: 3 }, { x: 4, y: 5 }]), "M0,1 M2,3 L4,5");
  assert.equal(areaPath([{ x: 0, y: 1 }, { x: 2, y: 3 }], 9), "M0,1 L2,3 L2,9 L0,9 Z");
  assert.equal(bandPath([{ x: 0, y: 1 }, { x: 2, y: 2 }], [{ x: 0, y: 5 }, { x: 2, y: 6 }]), "M0,1 L2,2 L2,6 L0,5 Z");
  const [lo, hi] = rangeBarDomain({ lo80: 100, hi80: 120, target_price: 125 }, 90, null);
  assert.ok(Math.abs(lo - 89.73) < 1e-9 && Math.abs(hi - 125.375) < 1e-9);
});

test("sorting is stable with missing values last", () => {
  const rows = [{ v: 2 }, { v: null }, { v: 1 }, { v: 2 }];
  assert.deepEqual(sortBy(rows, (r) => r.v, 1).map((r) => r.v), [1, 2, 2, null]);
  assert.deepEqual(sortBy(rows, (r) => r.v, -1).map((r) => r.v), [2, 2, 1, null]);
  assert.equal(sortBy(rows, (r) => r.v, -1)[0], rows[0]);
});
