"""Source cards are evidence for review at use, not legal approval."""


def citation_for(row, start, end, article=None):
    facts = row.pop('provenance', {})
    card = {key: row.get(key) for key in
            ('title', 'source_url', 'version_id', 'region', 'fetched_at',
             'review_state', 'availability', 'effective_from', 'effective_to', 'locator')}
    card.update({key: facts.get(key) for key in
                 ('publisher', 'original_url', 'original_sha256', 'source_format', 'document_number')})
    card.update(text_sha256=row['sha256'], article=article,
                character_range={'start': start, 'end': end},
                pages=[page['page'] for page in facts.get('pages', [])
                       if start < end and start < page['end'] and end > page['start']],
                uncompared_alternative_urls=facts.get('uncompared_alternative_urls', []),
                compared_pdf_originals=facts.get('compared_pdf_originals', []),
                source_dates=facts.get('source_dates', {}),
                source_dates_verified=False,
                review_at_use_required=True, legal_applicability_verified=False)
    card['missing_fields'] = [key for key in ('publisher', 'original_url', 'original_sha256',
                                             'document_number', 'effective_from', 'effective_to')
                              if card[key] is None]
    card['notice'] = ('可检索不等于已核验。实际引用须展示本来源卡、原文片段与条款/页码；'
                      '缺失字段明确未知，来源日期不等于已确认适用日期。'
                      '由使用者在引用时审阅版本、上下文及案件适用性。')
    if 'collection_id' in facts:
        card.update({key: facts.get(key) for key in
                     ('collection_id', 'attachment_id', 'parent_notice', 'verified_sources',
                      'internal_number', 'internal_title', 'differences', 'comparison_notice',
                      'original_path', 'structure_path', 'locations_path', 'check_scope',
                      'source_dates_scope', 'source_dates_url')})
        card['locations'] = [loc for loc in facts.get('locations', [])
                             if start < end and start < loc['end'] and end > loc['start']]
        card['notice'] += '表格引用须核对工作表、行、单元格及合并锚点；网页附件标号与文件内标号分别保留，冲突未经人工裁定。'
        if facts.get('source_format') in ('xls', 'xlsx'):
            card['notice'] += ('检索正文由原格内容与生成的定位标签组成；坐标和合并上下文不是官方新增正文。'
                               '原件SHA与检索正文SHA分别保存；引用按原件格位复核raw_text和display_text。')
    if card['availability'] == 'withdrawn':
        card['notice'] = '此版本已撤回，不得作为正常引用依据；仅供历史审计。' + card['notice']
    return card
