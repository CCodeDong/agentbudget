# AGC 发布证书与 Profile 申请指南

> **这件事我做不了**——需要你的华为账号登录。但下面每一步都写到了"点哪里、填什么"。
>
> 为什么现在就要做：**它同时是 L3 验证（装到设备）和最终上架的前置**。

---

## 一、你要申请的到底是什么

AppGallery 上架需要三样东西，缺一不可：

| 东西 | 是什么 | 谁生成 |
|---|---|---|
| **密钥库 `.p12`** | 你的私钥容器 | **你自己生成**（本地） |
| **证书 `.cer`** | 证明公钥属于你 | AGC 签发 |
| **Profile `.p7b`** | 绑定「这个应用 + 这些设备/权限」 | AGC 签发 |

**`.p12` 一旦丢失，应用永远无法发布更新。** 必须离线备份，且**绝不能进 git**（`.gitignore` 已排除）。

---

## 二、准备工作（5 分钟）

### 2.1 确认开发者账号已实名

- 登录 [AppGallery Connect](https://developer.huawei.com/consumer/cn/service/josp/agc/index.html)
- 右上角头像 → **账号中心** → 确认**实名认证**状态为"已认证"

> 我们配调试签名时已经做过一次实名，应该已就绪。

### 2.2 确认包名

**本项目决定用的包名是：**

```
com.xjtu.offlinelib
```

> ⚠️ **包名一旦在 AGC 建了应用就不能改。** 它同时出现在三处，必须完全一致：
> 1. `app/offlinelib/AppScope/app.json5` 的 `bundleName`
> 2. AGC 里新建应用时填的包名
> 3. Profile 绑定时的包名
>
> **如果你想换一个名字，现在是最后的窗口。**

---

## 三、第一步：在 AGC 新建应用

1. [AGC](https://developer.huawei.com/consumer/cn/service/josp/agc/index.html) → **我的应用**
2. 点 **新建应用**
3. 填写：

| 字段 | 填什么 |
|---|---|
| 应用名称 | **离线资料库** |
| 应用包名 | **`com.xjtu.offlinelib`** |
| 应用分类 | **工具** / **效率**（不要选教育、金融、医疗、新闻、直播、游戏、社交） |
| 默认语言 | 简体中文 |
| 是否游戏 | 否 |

4. 提交

> **类目选择很重要**：部分类目**个人开发者不可上架**。工具/效率类是安全选择。

---

## 四、第二步：生成密钥库 `.p12`（本地操作）

### 方法 A：用 DevEco Studio（推荐，图形界面）

1. DevEco 打开 `app/offlinelib`
2. **File → Project Structure → Signing Configs**
3. 取消勾选 **Automatically generate signature**（我们要手动配发布证书）
4. 点 **Store File** 那一行的 **Generate** 或 **Create**
5. 填写：

| 字段 | 建议值 |
|---|---|
| Keystore 路径 | **放在仓库外**，例如 `D:\keys\offlinelib.p12` |
| 密码 | **用密码管理器生成并保存** |
| Alias | `offlinelib_release` |
| 有效期 | 25 年（越长越好） |

> ⚠️ **不要把 `.p12` 放在项目目录里**——虽然 `.gitignore` 排除了它，但放在仓库外更安全。

### 方法 B：命令行（如果你更熟 keytool）

```powershell
keytool -genkeypair -alias offlinelib_release -keyalg EC -groupname secp256r1 `
  -dname "CN=Xi'an Jiaotong University, OU=Student, O=XJTU, L=Xi'an, C=CN" `
  -keystore D:\keys\offlinelib.p12 -storetype PKCS12 -validity 9125
```

---

## 五、第三步：申请证书 `.cer`

1. AGC → **证书、Profile 管理** → **证书** 标签
2. 点 **新增证书**
3. 填写：

| 字段 | 填什么 |
|---|---|
| 证书名称 | `offlinelib-release` |
| 证书类型 | **发布证书** |
| 上传 CSR | 见下 |

### 怎么生成 CSR

**用 DevEco**：上一步创建密钥库时，DevEco 会一并生成 `.csr` 文件
（通常在密钥库同目录，或点 **Generate CSR** 按钮）。

**用命令行**：
```powershell
keytool -certreq -alias offlinelib_release -keystore D:\keys\offlinelib.p12 `
  -file D:\keys\offlinelib.csr
```

4. 上传 `.csr` → 提交
5. 审核通过后**下载 `.cer`**

> 发布证书通常**几分钟内**签发，不需要长时间等待。

---

## 六、第四步：申请 Profile `.p7b`

1. AGC → **证书、Profile 管理** → **Profile** 标签
2. 点 **新增**
3. 填写：

| 字段 | 填什么 |
|---|---|
| Profile 名称 | `offlinelib-release` |
| 应用 | 选你在第三步新建的「离线资料库」 |
| 类型 | **发布** |
| 证书 | 选上一步的 `offlinelib-release` |

4. **权限选择**（关键）：

| 权限 | 我们是否需要 |
|---|---|
| `ohos.permission.CAMERA` | ✅ 拍照导入需要 |
| `ohos.permission.READ_IMAGEVIDEO` | ✅ 从相册选图需要 |
| `ohos.permission.READ_WRITE_DOWNLOAD_DIRECTORY` | ✅ 从文件导入需要 |
| **`ohos.permission.INTERNET`** | ❌ **绝对不要勾** |

> **不勾 `INTERNET` 是我们的核心主张**——它让"数据不出设备"从口号变成权限层面的事实。
> 这一点在答辩和上架材料里都要强调。

5. 提交 → **下载 `.p7b`**

---

## 七、第五步：配置到工程里

拿到三个文件后：

| 文件 | 建议位置 |
|---|---|
| `offlinelib.p12` | `D:\keys\`（仓库外） |
| `offlinelib.cer` | `D:\keys\` |
| `offlinelib.p7b` | `D:\keys\` |

然后告诉我，我把它配进 `app/offlinelib/build-profile.json5` 的 `signingConfigs`，
之后一条命令就能打包安装。

> 你也可以自己在 **Project Structure → Signing Configs** 里填。

---

## 八、这一步完成后能解锁什么

| 解锁 | 说明 |
|---|---|
| **L3 验证** | 能装到模拟器/真机，跑设备内自测 |
| **L4 验证** | 有真机时可以测真实 OCR |
| **上架** | 上架必须用发布签名的包 |

**所以这一步是多个事情共同的前置，值得优先做。**

---

## 九、时间预期

| 步骤 | 耗时 |
|---|---|
| 新建应用 | 5 分钟 |
| 生成 `.p12` | 5 分钟 |
| 申请证书 | 提交后几分钟到几小时 |
| 申请 Profile | 同上 |
| **总计** | **约 1 小时内可完成** |

> **不需要像软著那样等几周。** 这是唯一一个"今天就能拿到"的合规材料。

---

## 十、需要你回我的

1. **包名确认**：`com.xjtu.offlinelib` 可以吗？还是想换？
2. **三个文件的路径**（不用发内容，只发路径）——我来配
3. **申请过程中卡在哪一步**

---

## 十一、诚实说明

- 上面的步骤是我**根据官方文档结构整理的**，没有实际操作过（我没有你的账号）
- **证书/Profile 的审核时间我无法保证**——官方说通常很快，但没有承诺
- 如果 AGC 界面与本文描述不一致（版本更新），**以 AGC 实际界面为准**，并把差异告诉我，我更新这份文档
