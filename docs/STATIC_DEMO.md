# 静态交互演示

- 项目演示：<https://rheeh.github.io/ttt/>
- 主页中的相同版本：<https://rheeh.github.io/projects/zhixing/>
- 主页项目卡片统一维护在主页仓库的 `src/data/profile.ts`。

## 体验范围

| 页面 | 可体验操作 |
| --- | --- |
| 个股研究 | 搜索 8 个样本、切换 60 / 120 日 K 线、查看开高低收、逐项评分与数据依据、加入自选、保存笔记 |
| 参考池与自选 | 按名称 / 代码 / 行业搜索、按 S/A/B/C 与类型筛选、增加或移出自选 |
| 股票对比 | 选择 2–3 个样本、比较 60 日归一化走势及七维评分 |
| 研究快照 | 保存行情摘要、评分明细、笔记、版本和规则指纹；去重并回看 |

板块雷达、真实数据接入、信号核验与 K 线训练在完整应用中运行，未在静态演示中模拟远端调用。

## 数据生成

`scripts/build_demo_data.py` 使用固定随机种子生成虚构名称、`DEMOxx` 代码及 120 日合成 OHLCV。日期仅排除周末，不代表真实交易所日历。MA5 / MA10 / MA20 来自同一条合成路径，最近日涨幅与收盘价一致。

样本通过生产代码中的 `ScoreInput` 与 `StrategyEngine` 计算，输出总分、等级、七维触发原因、策略版本和规则指纹。分数保留原始累计尺度，未转换成百分制或预测概率。

重新生成并检查：

```bash
.venv/bin/python scripts/build_demo_data.py
node --check demo/data.js
node --check demo/app.js
```

生成不访问网络，不读取行情缓存、自选数据库、研究记录或凭据。修改样本结构或内容时，同时更新生成器中的 `version`，以区分新旧快照。`demo/data.js` 应与生成器一起提交。

## 运行与状态

```bash
python3 -m http.server 4178 --directory demo
```

打开 <http://localhost:4178>。HTML、CSS、JavaScript 和图标均使用相对路径，可直接托管在 GitHub Pages 子路径下，也可通过 `demo/index.html` 打开。资源不依赖 CDN、行情接口或第三方字体。

自选和快照使用当前来源的 `localStorage`，键为 `zhixing-static-demo-v1`。不同来源的本地与线上预览各自保存状态；同一来源的 `/ttt/` 与 `/projects/zhixing/` 共享演示记录。最多保留 20 份快照。存储不可用时转为当前页面内存状态，并显示反馈。重置仅修改演示专用键。

## 发布与主页同步

项目仓库通过 `gh-pages` 分支发布演示，Pages 构建来源为该分支的根目录。发布分支只包含五个演示资源与 `.nojekyll`，不包含后端或本地数据。

在验证并提交源码后，使用已登录的 GitHub CLI 推送演示：

```bash
python3 scripts/publish_demo.py
```

脚本从当前 `demo/` 复制资源，在临时目录中创建发布提交，并通过普通推送更新 `gh-pages`；保留发布历史，不使用强制推送。主分支提交后需要执行该脚本，Pages 随发布分支更新而重新部署。

主页使用相同静态资源，保持单一源文件：

```bash
python3 scripts/sync_demo_to_portfolio.py /path/to/portfolio
```

同步目标是主页仓库的 `public/projects/zhixing/`。主页项目卡片链接到 `/projects/zhixing/`；资源随主页现有的构建和 Pages 流程发布。更新演示后应同步、提交并发布两个仓库。
