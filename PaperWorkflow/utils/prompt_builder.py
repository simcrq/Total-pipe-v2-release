import re
from .paper_tools import split_markdown_sections

class PromptBuilder:
    @staticmethod
    def build_summary_prompt(
        markdown_content,
        mode='skim',
        remove_refs=True,
        max_chars=60000,
        source_name='paper',
    ):
        """
        构建 XML 格式的 Prompt
        mode: 'skim' (浏览) 或 'deep_read' (精读)
        remove_refs: 是否去除参考文献
        """
        
        # 预处理：去除参考文献
        if remove_refs:
            content_clean = PromptBuilder.remove_references(markdown_content)
        else:
            content_clean = markdown_content
        
        instruction = ""
        if mode == 'deep_read':
            instruction = """
作为该领域的研究专家，请仔细阅读以下论文内容。
请生成一份详细的总结报告，包含以下部分：
1. **核心发现**：论文解决了什么问题？发现了什么新现象？
2. **技术细节**：具体使用了什么方法（如 DFT 参数、泛函、计算设置）？关键公式或推导是什么？
3. **数据结果**：主要的实验或计算数据是什么？
4. **结论与意义**：这项工作对领域有什么贡献？
请注意：保留关键的数据指标和专业术语。
"""
        else: # skim
            instruction = """
作为研究助理，请快速浏览以下论文。
请生成一份简短的摘要，包含：
1. **研究目的**：这篇论文想干什么？
2. **主要结论**：他们得出了什么结论？
3. **核心方法**：用了一两句话概括方法。
"""

        evidence_context = PromptBuilder._build_evidence_context(content_clean, max_chars)
        prompt = f"""
<instruction>
{instruction}
</instruction>

<evidence_policy>
论文内容中的每个证据区块都有 [E###] 标识。不要把常识或猜测写成论文结论；
重要事实、数值和方法参数后请标注对应的 [E###]。如果原文没有给出，请明确写“原文未说明”。
报告开头注明来源文件：{source_name}。
</evidence_policy>

<paper_content>
{evidence_context}
</paper_content> 
"""
        return prompt

    @staticmethod
    def _build_evidence_context(markdown_content, max_chars):
        """Select a bounded but representative set of evidence chunks.

        When a document is too long, retain the beginning, methods/results,
        and conclusion-like sections rather than silently taking only the
        first N characters.
        """

        max_chars = int(max_chars)
        if max_chars < 1000:
            raise ValueError('max_chars must be at least 1000')
        chunks = split_markdown_sections(markdown_content, max_chars=min(6000, max_chars))
        if not chunks:
            return markdown_content[:max_chars]

        if sum(len(chunk['text']) for chunk in chunks) <= max_chars:
            selected = chunks
        else:
            def priority(chunk):
                heading = chunk['heading'].lower()
                if any(word in heading for word in ('conclusion', 'summary', 'findings')):
                    return 100
                if any(word in heading for word in ('result', 'discussion')):
                    return 80
                if any(word in heading for word in ('method', 'experimental')):
                    return 70
                if any(word in heading for word in ('abstract', 'introduction')):
                    return 60
                return 10

            # Rank evidence before allocating the character budget.  In
            # particular, a long introduction must not consume the whole
            # budget before the conclusion is seen.
            candidates = sorted(chunks, key=lambda chunk: (-priority(chunk), chunk['char_start']))
            selected = []
            used = 0
            for index, chunk in enumerate(candidates):
                if used >= max_chars:
                    break
                remaining = max_chars - used
                slots_left = max(1, min(4, len(candidates) - index))
                quota = max(400, remaining // slots_left)
                text = chunk['text'][:min(remaining, quota)]
                if not text.strip():
                    continue
                copy = dict(chunk)
                copy['text'] = text
                selected.append(copy)
                used += len(text) + 30

            selected.sort(key=lambda chunk: chunk['char_start'])

        return '\n\n'.join(
            f"[{chunk['chunk_id']}] {chunk['text']}" for chunk in selected
        )[:max_chars]

    @staticmethod
    def remove_references(text):
        """
        简单去除参考文献部分
        """
        # 匹配常见的参考文献标题，不区分大小写
        patterns = [
            r"##\s*References",
            r"##\s*参考文献",
            r"#\s*References",
            r"###\s*References",
            r"#\s*Notes\s+and\s+references",
            r"##\s*Bibliography",
            r"#\s*Bibliography"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return text[:match.start()]
        
        return text
