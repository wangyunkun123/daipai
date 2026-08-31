import React from 'react';
import { StyleSheet } from 'react-native';
import { Canvas, Rect, Circle, Line } from '@shopify/react-native-skia';
import { colors } from '../theme/tokens';
import type { PlanAnnotation } from '../api/types';

interface Props {
  width: number;
  height: number;
  annotations?: PlanAnnotation[];
}

/**
 * 在照片上画方案标注。坐标按 0-1 归一化（后端模型可能输出像素坐标，
 * 若某值 >1 则视为像素按容器归一化，做容错）。
 * subject → 暖金矩形框；shooter → 暖金圆点 + 十字。
 * 极淡描边，不挡脸。
 */
export function SketchAnnotation({ width, height, annotations = [] }: Props) {
  const norm = (v: number, bound: number) => (v > 1 ? v / bound : v);
  // 坐标非法（NaN/非数字/负值/字符串）时跳过该项，避免画到画布外
  const hasPos = (a: PlanAnnotation) =>
    typeof a.x === 'number' && isFinite(a.x) && typeof a.y === 'number' && isFinite(a.y);

  return (
    <Canvas style={[StyleSheet.absoluteFill, { width, height }]} pointerEvents="none">
      {annotations.map((a, i) => {
        if (!hasPos(a)) return null;
        const cx = norm(a.x, width) * width;
        const cy = norm(a.y, height) * height;
        if (a.type === 'subject') {
          return (
            <Rect
              key={i}
              x={cx - 40}
              y={cy - 60}
              width={80}
              height={120}
              color={colors.guideGold}
              style="stroke"
              strokeWidth={1.5}
              opacity={0.8}
            />
          );
        }
        return (
          <React.Fragment key={i}>
            <Circle cx={cx} cy={cy} r={8} color={colors.guideGold} style="stroke" strokeWidth={1.5} />
            <Line
              p1={{ x: cx - 14, y: cy }}
              p2={{ x: cx + 14, y: cy }}
              color={colors.guideGold}
              strokeWidth={1.5}
            />
            <Line
              p1={{ x: cx, y: cy - 14 }}
              p2={{ x: cx, y: cy + 14 }}
              color={colors.guideGold}
              strokeWidth={1.5}
            />
          </React.Fragment>
        );
      })}
    </Canvas>
  );
}
