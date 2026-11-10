import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import type { MetricsMsg } from "../protocol";

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

export function TrendChart({ trend }: { trend: MetricsMsg["trend"] }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    chart.current = echarts.init(ref.current!, undefined, { renderer: "canvas" });
    const onResize = () => chart.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.current?.dispose();
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !trend) return;
    const series = (src: string) =>
      trend.filter((p) => p.source === src).map((p) => [p.ts, p.cnt] as [number, number]);
    chart.current.setOption({
      animation: false,
      grid: { left: 36, right: 30, top: 24, bottom: 22 },
      tooltip: { trigger: "axis" },
      legend: { data: ["维基编辑/分", "地震/分"], textStyle: { color: "#9fb3c8", fontSize: 10 }, top: 0, right: 0 },
      xAxis: { type: "time", axisLabel: { color: "#6b7f99", fontSize: 10 }, axisLine: { lineStyle: { color: "#23324a" } } },
      yAxis: [
        { type: "value", axisLabel: { color: "#6b7f99", fontSize: 10 }, splitLine: { lineStyle: { color: "#152238" } } },
        { type: "value", axisLabel: { color: "#6b7f99", fontSize: 10 }, splitLine: { show: false }, minInterval: 1 },
      ],
      series: [
        { name: "维基编辑/分", type: "line", showSymbol: false, smooth: true, data: series("wiki"), lineStyle: { color: "#40f0ff", width: 2 }, areaStyle: { color: "rgba(64,240,255,0.12)" } },
        { name: "地震/分", type: "line", yAxisIndex: 1, step: "middle", showSymbol: false, data: series("usgs"), lineStyle: { color: "#ff4433", width: 1.5 } },
      ],
    });
  }, [trend]);

  return <div ref={ref} className="trend" />;
}
