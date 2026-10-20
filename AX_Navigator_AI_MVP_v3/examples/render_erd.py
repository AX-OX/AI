#!/usr/bin/env python3
"""Render a standalone schema sheet. Requires Pillow; SQL is authoritative.
Foreign keys are labelled at the source with target table/column, including composite FK.
"""
import json
import os
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]

def main():
    graph=json.loads((ROOT/'erd/schema_graph.json').read_text())
    tables=graph['tables'];links=graph['links']
    fontfile=os.getenv('ERD_FONT','/System/Library/Fonts/Supplemental/Arial.ttf')
    if not Path(fontfile).exists(): fontfile='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    def font(size):return ImageFont.truetype(fontfile,size)
    heading=font(54);title=font(29);body=font(23);small=font(20)
    width=4400; margin=70;gap=35;cardw=(width-2*margin-3*gap)//4;cardh=690
    height=margin+180+4*(cardh+gap)+90
    canvas=Image.new('RGB',(width,height),'#f2f5fa');draw=ImageDraw.Draw(canvas)
    draw.text((margin,margin),'AX Navigator AI | v3 schema',font=heading,fill='#15283d')
    draw.text((margin,margin+75),'Business: 14 tables / 24 FKs     RAG pgvector: 2 tables / 3 FKs     Total ax: 16 tables / 27 FKs',font=title,fill='#37516e')
    draw.text((margin,margin+120),'PK = primary key; FK > target shows referenced columns. RAG tables are green. Full defaults / nullability / checks: SQL.',font=body,fill='#52677e')
    order=['companies','departments','business_processes','process_metrics','it_systems','process_systems','documents','ai_solution_catalog','users','ai_tasks','ax_assessments','ax_roadmaps','roadmap_items','ax_projects','rag_indexes','rag_document_chunks']
    pks={name:[cols[0][0]] for name,cols in tables.items()}
    pks.update(process_systems=['process_id','system_id'],ai_tasks=['task_id'],rag_indexes=['company_id','index_version'],rag_document_chunks=['company_id','index_version','chunk_id'])
    for idx,name in enumerate(order):
        col=idx%4;row=idx//4
        x=margin+col*(cardw+gap); y=margin+180+row*(cardh+gap)
        rag=name.startswith('rag_');color='#116f5b' if rag else '#245a91'
        draw.rounded_rectangle((x,y,x+cardw,y+cardh),radius=16,fill='white',outline='#ccd8e5',width=2)
        draw.rounded_rectangle((x,y,x+cardw,y+58),radius=16,fill=color)
        draw.rectangle((x,y+30,x+cardw,y+58),fill=color)
        draw.text((x+20,y+13),name,font=title,fill='white')
        for j,(column,typ) in enumerate(tables[name]):
            marker='PK ' if column in pks[name] else '   '
            draw.text((x+18,y+74+j*25),marker+column,font=body,fill='#1d354e')
            draw.text((x+cardw-220,y+76+j*25),typ,font=small,fill='#5d7288')
        foreign=[(s,c,t,k) for s,c,t,k in links if s==name]
        yy=y+cardh-28-len(foreign)*26
        for _,src,target,columns in foreign:
            label=f'FK {src} > {target}.{columns}'
            if draw.textlength(label,font=small)>cardw-40:
                label=f'FK ({src}) > {target}'
            draw.text((x+20,yy),label,font=small,fill=color);yy+=26
    draw.text((margin,height-60),'PostgreSQL 16 target + pgvector 0.8.1 | vector(384) | ax data only; agent checkpointer DB excluded | Synthetic sample',font=body,fill='#52677e')
    canvas.save(ROOT/'erd/AX_Navigator_v3.png',optimize=True)
if __name__=='__main__':main()
