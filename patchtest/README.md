# auto-merge.yml 的补丁 / a patch for auto-merge.yml

这个目录里的 `auto-merge.yml` 是 `.github/workflows/auto-merge.yml` 的**替换版**，
修了 #17 报的三个问题。因为 `.github/` 是受保护路径，AI 不能改，
所以补丁放在这里等人来取。

This `auto-merge.yml` is a drop-in replacement for `.github/workflows/auto-merge.yml`,
fixing the three problems in #17. `.github/` is a protected path, so no AI may change
it — the patch waits here for a human.

## 怎么用 / How to apply

```bash
cp patchtest/auto-merge.yml .github/workflows/auto-merge.yml
git checkout -b fix/auto-merge
git add .github/workflows/auto-merge.yml
git commit -m "fix: 机器人在失败和空提交的时候都不说话"
git push origin fix/auto-merge
gh pr create --fill
```

机器人会拒绝合并这个 PR（它改了 `.github/`），这是对的 —— 所以需要人手动合。

## 修了什么 / What it fixes

### 一、失败时说出来

原来失败只有一行 `::warning::`，只出现在 Actions 日志里。`#12` 卡了五十多分钟、
零条评论，作者根本不知道。

现在失败会 `gh pr comment` 到 PR 上，附上 `gh` 的原始报错，并且说清楚最常见的
原因（和 `main` 冲突）和一个不需要 git 的解法。

### 二、空提交拒绝合并

同一个分支开两个 PR 时必然产生空提交：第一个合完，第二个的 `base` 已经包含了
它的全部内容，而 `gh pr merge --squash` **仍然返回成功**。`#19` 和 `#23` 就是这样
进的 `main`。

判据只能比 **tree**：

```
base_tree == head_tree  →  内容已经在 main 里了，跳过并评论
```

不能用 `gh pr view --json files` —— 那是相对 merge-base 的三点 diff，
base 已经包含 head 时它仍然显示改动。这正是我一开始写错的地方。

用真实历史验过：

| PR | base tree | head tree | 判定 | 对不对 |
|---|---|---|---|---|
| #16 | 7f25f6f63b | b253ecb4da | merge | ✔ |
| #18 | b253ecb4da | 74f96ceab0 | merge | ✔ |
| #19 | 74f96ceab0 | 74f96ceab0 | **skip** | ✔ |
| #20 | 74f96ceab0 | b68bb52042 | merge | ✔ |
| #29 | 66986e7609 | a79a1b3d87 | merge | ✔ |

### 三、`--match-head-commit`

`gh pr merge` 有这个参数：如果 head 在合并前又变了，就拒绝。

防的是我实际撞上的一件事：`--amend` 之后 push 被拒，但 PR 早就用旧分支建好了，
机器人照样按旧 head 合了 —— **我改的三处一个都没进 main**（见 #24 → #26）。

带上 `--match-head-commit "$head_sha"`，这种情况会失败而不是静默合错东西。

## 没验到的 / What is NOT verified

- **没在真的 Actions 里跑过。** 这个环境没有 `gh`，也没有 Actions。我验的是
  YAML 结构、`bash -n` 语法、以及判据在真实历史数据上的结果。
- `gh pr view --json baseRefOid,headRefOid,isDraft` 的字段名按 `gh` 官方手册写的，
  但没实测过这个组合。
- `gh pr merge` 失败时的报错文本我用 `case` 匹配了 `already merged` /
  `not mergeable`，这些字符串是从实际日志里看到的（`#12` 那次），但不是穷举。

**所以这个补丁需要在合并前由人看一眼**，最好在 `workflow_dispatch` 上先手动触发一次
试试。

## 改动很小

原来 60 行的 run 块，现在 98 行。没有引入任何新的 action 或 secret。
