# 知行股研

一个独立开发、仅限个人使用的 A 股研究工具。它保留固定观察池、S/A/B/C 经验评分、轮动加分和个人价格区间，但不连接券商、不执行交易。

当前已完成第一个纵向闭环：

- 可版本化的个人策略 JSON；
- 确定性评分引擎，输出维度分、总分、等级和过滤原因；
- SQLite 长期保存预选股；
- FastAPI 本地 API，只监听 `127.0.0.1`；
- React 桌面工作台原型，支持评分和加入观察。

## 本地启动

需要 Python 3.11+ 和 Node.js 20+。

```bash
./scripts/bootstrap.sh
./scripts/dev.sh
```

启动后：

- 前端：<http://127.0.0.1:5173>
- API 文档：<http://127.0.0.1:8765/docs>

## 验证

```bash
./scripts/verify.sh
```

## 数据与安全

数据库默认保存在当前用户的本地应用数据目录，不会提交到 Git。仓库不包含 API Key，也没有券商、委托、撤单或自动下单代码。

详细评估和分期路线见 [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)。

