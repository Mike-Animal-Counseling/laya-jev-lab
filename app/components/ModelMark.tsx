import Icon from "./Icon";
import type { Provider } from "../lib/tickets";
export default function ModelMark({ provider }: { provider: Provider }) {
  return (
    <span className={`model-mark ${provider === "jev" ? "is-jev" : ""}`}>
      <Icon name={provider === "jev" ? "cloud" : "chip"} size={17} />
    </span>
  );
}
