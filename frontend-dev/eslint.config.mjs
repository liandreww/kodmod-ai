// eslint-config-next 16 ships a flat config array directly; no FlatCompat needed.
import next from "eslint-config-next";

export default [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...next,
];
