# 代码块表格配方 + 截图插入(基于内置 docx skill「编辑现有文档」)

排版**复用内置 docx skill**,走它的「编辑现有文档」三步:
1. `python <docx-skill>/scripts/office/unpack.py template.docx unpacked/`
2. 编辑 `unpacked/word/document.xml`(用 Edit 工具做字符串替换,**不要写 Python 改 XML**)
3. `python <docx-skill>/scripts/office/pack.py unpacked/ report.docx --original template.docx`

`fill_report.py` 负责生成「要插入的 XML 片段」并定位插入点;实际写入用 Edit 工具,最后 `pack.py` 校验。

## 代码块 = 单元格底色淡金的表格(嵌在正文单元格内)

把每段命令/代码渲染成一个**单行单列表格**,塞进「实验过程/结论」对应的 `<w:tc>` 里。硬性样式:
- 底色 **#FFF2CC**(淡金),`type="clear"` —— 对应 docx skill 的 **`ShadingType.CLEAR`**;
  **绝不用 `solid`**,否则在部分阅读器里变**黑底**。
- 字体 **Consolas**,字号 **五号 = 10.5pt**(OOXML 的 `w:sz` 用半点,故 `w:sz w:val="21"`);
  **超长行降 9pt**(`w:sz w:val="18"`)免撑破(匹配样例对 sftp/put 长行的处理)。
- 边框:**single `sz=4` `#000000`(细黑)**,匹配样例(非旧的淡金 `D9C27A`)。
- **宽度 auto(随内容)**:表格 `<w:tblW w:w="0" w:type="auto"/>`、单元格 `<w:tcW w:w="0" w:type="auto"/>`。
  **不再用「双重固定宽 + `tblLayout fixed`」强制定宽**——auto 让短命令小框、长命令撑满,匹配样例。
- 每行代码一个 `<w:p>`(OOXML 不能用 `\n`,多行=多段),保留缩进。

### 可直接套用的 XML 片段(单格代码块)
```xml
<w:tbl>
  <w:tblPr>
    <w:tblW w:w="0" w:type="auto"/>                  <!-- 宽度 auto:随内容,短命令小框、长命令撑满 -->
    <w:tblBorders>
      <w:top w:val="single" w:sz="4" w:color="000000"/>
      <w:left w:val="single" w:sz="4" w:color="000000"/>
      <w:bottom w:val="single" w:sz="4" w:color="000000"/>
      <w:right w:val="single" w:sz="4" w:color="000000"/>
    </w:tblBorders>
    <!-- 不设 tblLayout fixed:auto 模式由内容决定列宽 -->
  </w:tblPr>
  <w:tr>
    <w:tc>
      <w:tcPr>
        <w:tcW w:w="0" w:type="auto"/>               <!-- 单元格也 auto,与表一致 -->
        <w:shd w:val="clear" w:color="auto" w:fill="FFF2CC"/>   <!-- clear 非 solid;淡金 -->
        <w:tcMar><w:top w:w="60"/><w:bottom w:w="60"/><w:left w:w="120"/><w:right w:w="120"/></w:tcMar>
      </w:tcPr>
      <!-- 每行代码一段;空格用 xml:space="preserve" 保住缩进 -->
      <w:p><w:pPr><w:spacing w:line="240" w:lineRule="auto"/></w:pPr>
        <w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="21"/></w:rPr>
          <w:t xml:space="preserve">sudo su -</w:t></w:r></w:p>
      <w:p><w:pPr><w:spacing w:line="240" w:lineRule="auto"/></w:pPr>
        <w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="21"/></w:rPr>
          <w:t xml:space="preserve">systemctl start mariadb</w:t></w:r></w:p>
    </w:tc>
  </w:tr>
</w:tbl>
```
> 这是**嵌套表格**(放在正文 `<w:tc>` 内)。嵌套表格后若紧跟内容,OOXML 要求其后跟一个空 `<w:p>`,
> 否则单元格结构非法 —— 在每个嵌套表格后补一个空段落。

## 截图插入(穿插进「实验过程」单元格)
按 docx skill 的图片三步:
1. PNG 放 `unpacked/word/media/`;
2. `unpacked/word/_rels/document.xml.rels` 加 `<Relationship .../image .../>`;
3. `[Content_Types].xml` 确保有 `<Default Extension="png" ContentType="image/png"/>`;
4. 在目标 `<w:tc>` 内用 `<w:drawing><wp:inline>` 引用(`<wp:extent>` 用 EMU:914400 = 1 英寸)。

排版顺序(铁律,匹配样例):**短说明句(上) → 代码块 → 结果截图(下)**,逐步骤重复,**全程无图注**
(说明句已交代这张图证明了什么)。
图片宽度 **≈15.5cm 满栏、左对齐、等比缩放**(样例实测 ≈15.49cm);**图下不加图注**。

## 其他来自 docx skill 的注意事项
- **不要把表格当分隔线/横线用**(空表格会渲染成空盒子)。
- 文本里的撇号/引号用智能引号实体(`&#x2019;` 等),见 docx skill 的实体表。
- 改完务必 `pack.py`(带校验);失败就按报错改 XML 再打包。
- 字号换算:OOXML `w:sz` 单位是**半点**——五号 10.5pt → `21`;小四 12pt → `24`;四号 14pt → `28`。
