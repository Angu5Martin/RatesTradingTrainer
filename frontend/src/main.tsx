import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./shell/App";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/desk.css";
import "./styles/shell.css";
import "./styles/train.css";
import "./styles/game.css";
import "./styles/guide.css";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
