import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART_COLORS, compact, money, num, shortDate, titleCase } from "../lib/format";

const axis = {
  stroke: "#475569",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

const tooltipStyle = {
  contentStyle: {
    background: "#0d1220",
    border: "1px solid #1e293b",
    borderRadius: 8,
    fontSize: 12,
    color: "#e2e8f0",
  },
  labelStyle: { color: "#94a3b8", fontSize: 11 },
};

export function RevenueArea({
  data,
  xKey = "order_date",
  height = 260,
}: {
  data: any[];
  xKey?: string;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey={xKey} {...axis} tickFormatter={shortDate} minTickGap={28} />
        <YAxis {...axis} tickFormatter={(v) => compact(v)} width={56} />
        <Tooltip
          {...tooltipStyle}
          formatter={(v: any, n: any) => [money(v), titleCase(n)]}
          labelFormatter={(l) => shortDate(l)}
        />
        <Area
          type="monotone"
          dataKey="revenue"
          stroke="#38bdf8"
          strokeWidth={2}
          fill="url(#rev)"
        />
        {data?.[0]?.revenue_7d_ma !== undefined && (
          <Area
            type="monotone"
            dataKey="revenue_7d_ma"
            stroke="#a78bfa"
            strokeWidth={1.5}
            fill="none"
            strokeDasharray="4 3"
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function SimpleBar({
  data,
  xKey,
  yKey,
  height = 260,
  horizontal = false,
  color = "#38bdf8",
  valueFormatter = money,
}: {
  data: any[];
  xKey: string;
  yKey: string;
  height?: number;
  horizontal?: boolean;
  color?: string;
  valueFormatter?: (v: any) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={horizontal ? "vertical" : "horizontal"}
        margin={{ top: 8, right: 16, left: horizontal ? 8 : 0, bottom: 0 }}
      >
        <CartesianGrid stroke="#1e293b" vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...axis} tickFormatter={(v) => compact(v)} />
            <YAxis
              type="category"
              dataKey={xKey}
              {...axis}
              width={120}
              tickFormatter={(v) => String(v).slice(0, 18)}
            />
          </>
        ) : (
          <>
            <XAxis dataKey={xKey} {...axis} tickFormatter={(v) => String(v).slice(0, 10)} />
            <YAxis {...axis} tickFormatter={(v) => compact(v)} width={56} />
          </>
        )}
        <Tooltip {...tooltipStyle} formatter={(v: any) => valueFormatter(v)} />
        <Bar dataKey={yKey} fill={color} radius={[4, 4, 0, 0]} maxBarSize={38} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Donut({
  data,
  nameKey,
  valueKey,
  height = 260,
  valueFormatter = money,
}: {
  data: any[];
  nameKey: string;
  valueKey: string;
  height?: number;
  valueFormatter?: (v: any) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey={valueKey}
          nameKey={nameKey}
          innerRadius="55%"
          outerRadius="82%"
          paddingAngle={2}
          stroke="#0d1220"
        >
          {data?.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip {...tooltipStyle} formatter={(v: any) => valueFormatter(v)} />
        <Legend
          verticalAlign="bottom"
          height={36}
          formatter={(v) => <span style={{ color: "#94a3b8", fontSize: 11 }}>{v}</span>}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function ForecastChart({
  data,
  height = 300,
}: {
  data: any[];
  height?: number;
}) {
  const merged = data?.map((r) => ({
    ...r,
    actual: r.y_actual ?? null,
    predicted: r.y_forecast ?? null,
  }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={merged} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey="ds" {...axis} tickFormatter={shortDate} minTickGap={32} />
        <YAxis {...axis} tickFormatter={(v) => compact(v)} width={56} />
        <Tooltip
          {...tooltipStyle}
          formatter={(v: any, n: any) => [money(v), titleCase(n)]}
          labelFormatter={(l) => shortDate(l)}
        />
        <Legend
          verticalAlign="top"
          height={28}
          formatter={(v) => <span style={{ color: "#94a3b8", fontSize: 11 }}>{v}</span>}
        />
        <Line
          type="monotone"
          dataKey="actual"
          name="actual revenue"
          stroke="#38bdf8"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
        <Line
          type="monotone"
          dataKey="predicted"
          name="forecast"
          stroke="#fbbf24"
          strokeWidth={2}
          strokeDasharray="5 4"
          dot={false}
          connectNulls
        />
        <Line
          type="monotone"
          dataKey="y_upper"
          name="upper band"
          stroke="#fbbf2455"
          strokeWidth={1}
          dot={false}
          connectNulls
        />
        <Line
          type="monotone"
          dataKey="y_lower"
          name="lower band"
          stroke="#fbbf2455"
          strokeWidth={1}
          dot={false}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function DualBarLine({
  data,
  xKey,
  barKey,
  lineKey,
  height = 280,
}: {
  data: any[];
  xKey: string;
  barKey: string;
  lineKey: string;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey={xKey} {...axis} tickFormatter={(v) => String(v).slice(0, 10)} />
        <YAxis {...axis} tickFormatter={(v) => compact(v)} width={56} />
        <Tooltip {...tooltipStyle} />
        <Bar dataKey={barKey} fill="#0ea5e9" radius={[4, 4, 0, 0]} maxBarSize={34} />
        <Line type="monotone" dataKey={lineKey} stroke="#fbbf24" strokeWidth={2} dot={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export { num, money, compact };
