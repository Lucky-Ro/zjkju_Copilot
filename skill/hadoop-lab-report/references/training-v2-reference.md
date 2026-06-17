# hadoop-training-v2(P2–P4)参考实现 —— 内置抽象代码 + 参数化 + canonical Hive SQL

training-v2 系列(`https://heisun.xyz/docs/hadoop-training-v2/hadoop-trainingNN/`,NN=02/03/04)是
**综合作业**:每人按花名册分到一个**演员**,围绕豆瓣电影库 `Film.json`(41960 部电影)做「写程序筛数据 +
Hive 分析 + 可视化」。本 skill 已把三套**权威参考工程**抽象成内置模板,**不再让大模型从零猜代码**——
按 `(学号后三位 sid3, 演员 actor)` 参数化后真跑即可。

> ⚠️ 演员从哪来:先 `python scripts/find_actor.py`(按 `lab_config.identity` 的姓名+学号在花名册
> `学生演员分配*.xlsx` 里匹配,写进 `identity.actor`)。脚本没命中再人工核对花名册兜底,**绝不瞎编**。

## Film.json 字段(三个 Part 通用)

| 字段 | 注释 | 字段 | 注释 |
|---|---|---|---|
| title | 电影名 | director | 导演 |
| year | 上映年份 | actor | 演员(逗号分隔多个) |
| type | 电影类型 | time | 电影时长 |
| star | 评分 2–10 | film_page | 电影信息链接(可当电影 ID) |

## 内置模板与 Part 映射(`assets/training-code/`)

| Part / 教程 | 模板目录 | 关键类 | 干啥 |
|---|---|---|---|
| **P2** training02 | `exp1/` | `MovieInfo`(WritableComparable)、`ActorBestMoviesMapper`、`ActorBestMoviesMain` | **MapReduce** 找我的演员评分最高的 5 部电影 |
| **P3** training03 | `exp2/` | `MovieInfo`(POJO)、`Json2CoActorCsv` | 筛我的演员电影转 CSV → **Hive** 找合作次数最多的前 5 位演员及合作最高分作品 |
| **P4** training04 | `exp3/` | `MovieInfo`(POJO)、`Json2ActorMovieCsv` | 筛我的演员电影转 CSV → **Hive** 按年份统计数量/平均分 → **可视化**(折线/柱状图) |

## 参数化规则(两个占位)

| 占位 | 替换为 | 出现处 |
|---|---|---|
| 包名 `hadoop9999`(9999=学号后三位占位) | `hadoop<sid3>` | `package` 声明、`src/main/java/hadoop9999/` 目录、pom `<mainClass>` |
| 字符串 `"我的演员"` / `ACTOR="我的演员"` | 本人分配到的演员 | exp1 `ActorBestMoviesMapper`、exp2 `Json2CoActorCsv`、exp3 `Json2ActorMovieCsv` |

**用脚本一步到位**(确定性、优先):

```
python scripts/prepare_training_project.py P3 --sid3 340 --actor 林雪
# → 从 assets/training-code/exp2 物化到 runs/t03/project/,包名改 hadoop340、ACTOR 设 林雪、
#   pom <mainClass> 同步、把资料库 Film.json 拷进 src/main/resources/
```

`--sid3`/`--actor` 缺省自动取 `lab_config.json` 的 `student_id_last3`/`identity.actor`。脚本报错再按本文件手工参数化兜底。

## 端到端流水线

1. **物化 + 参数化工程**:`prepare_training_project.py <P2|P3|P4>` → `runs/tNN/project/`(已是 `hadoop<sid3>` 包、真实演员)。
2. **准备数据**:`Film.json` 已被脚本拷进 `src/main/resources/`(纯 Java 的 P3/P4 从 classpath 读)。
3. **打包**:工程目录 `mvn -q -DskipTests package` → `target/*.jar`。
4. **跑程序**:
   - **P3/P4(纯 Java)**:`java -cp target/classes;<fastjson.jar> hadoop<sid3>.training.exp2.Json2CoActorCsv`
     (或直接在 IDEA 跑 main),产出 `CoActor.csv` / `ActorMovie.csv` 到 resources 目录。
   - **P2(MapReduce)**:先把 `fastjson-1.2.62.jar` 上传到 **HDFS `/lib/`**、`Film.json` 上传到 HDFS 输入目录,
     再 `hadoop jar target/<jar> <输入Film.json> <输出目录>`;输出已按评分(同分年份近者优先)排序,取前 5。
5. **导入 Hive 分析**:把 CSV 上传 HDFS → `hive` 里建表 `load data` → **逐条**跑下面的 canonical SQL(真交互、每条一张截图)。
6. **P4 可视化**:把年度统计结果(year, 数量, 平均分)用 Excel 等做折线/柱状图(manual,图放 `runs/t04/manual/`)。

## Canonical Hive SQL(直接采用,演员值用 `apply_actor` 代入)

### P3(training03)合作演员分析 —— 表 `film_actor(id,tit,actor,star,year)`

```sql
-- 建表(CoActor.csv:film_page, title, actor, star, year)
create table film_actor(id string,tit string,actor string,star float,year int)
  row format delimited fields terminated by ',';
-- 导入(把 CSV 先传到 HDFS,这里 inpath 写其 HDFS 路径)
load data inpath '/path/to/CoActor.csv' into table film_actor;

-- 创建视图前,避免中文乱码:先在 MariaDB(Hive 元数据库)执行一次
--   alter table TBLS modify column VIEW_EXPANDED_TEXT mediumtext character set utf8;
--   alter table TBLS modify column VIEW_ORIGINAL_TEXT mediumtext character set utf8;

-- 合作演员次数 + 排名(排除我的演员自己;<我的演员> 由 apply_actor 代入真实演员)
create view actor_count as (
  select actor,n,rank() over (order by n desc) as rk from (
    select actor,count(*) as n from film_actor where actor<>'我的演员' group by actor order by n desc
  ) acc
);
select * from actor_count where rk<=5;

-- 每位演员评分最高、年份靠前的作品,存视图
create view actor_best_film as
  select * from (
    select *,row_number() over(partition by actor order by star desc,year desc) as rk from film_actor
  ) ab where rk=1;

-- 合作次数前 5 的演员 + 合作最高分作品(姓名/次数/作品/评分/年份)
select a.actor,a.n,b.tit,b.star,b.year
from actor_count a left join actor_best_film b on a.actor=b.actor
where a.rk<=5;
```

### P4(training04)年度产量与质量 —— 表 `actormov(id,name,star,year)`

```sql
-- 建表(ActorMovie.csv:film_page, title, star, year)
create table actormov(id string,name string,star float,year int)
  row format delimited fields terminated by ',';
load data inpath '/path/to/ActorMovie.csv' into table actormov;

-- 按年统计:上映数量 n、平均分 avgstar(保留 1 位)
select year,count(*) as n,round(avg(star),1) as avgstar
from actormov group by year order by year asc;
```

把这张 `(year, n, avgstar)` 结果导出做折线图(平均分)/柱状图(数量)即为 P4 的可视化交付。

## 报告排版

training 报告用专属模板 `assets/training_template.docx`(见 `references/report-template.md` 的
「training-v2 实训报告映射」)。正文里出现的演员、学号占位分别由 `apply_actor`、`apply_sid` 替换到位。
