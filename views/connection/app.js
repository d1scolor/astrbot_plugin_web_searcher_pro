const button = document.getElementById("test");
const status = document.getElementById("status");
const output = document.getElementById("result");
const bridge = window.AstrBotPluginView;

try {
  if (!bridge) throw new Error("Missing Dashboard bridge");
  await bridge.ready();
  button.disabled = false;
  status.textContent = "就绪。测试使用已保存并加载的配置。";
} catch {
  status.textContent = "请从 AstrBot 插件详情页打开此视图，并尝试重载插件。";
}

button.addEventListener("click", async () => {
  button.disabled = true;
  output.hidden = true;
  status.textContent = "正在测试健康状态、鉴权和扫描接口…";
  try {
    const response = await bridge.apiPost("guard/test", {});
    const report = response?.data ?? response;
    status.textContent = report.ok ? "连接测试通过 / Connection passed" : "连接测试失败 / Connection failed";
    output.textContent = JSON.stringify(report, null, 2);
    output.hidden = false;
  } catch {
    status.textContent = "测试请求失败。请确认 Dashboard 登录状态并重载插件。";
  } finally {
    button.disabled = false;
  }
});
