import {Fragment,type ReactNode} from 'react';
import {Icon} from './Icon';
function inline(text:string):ReactNode[]{return text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/g).map((part,i)=>{if(part.startsWith('`')&&part.endsWith('`'))return <code key={i}>{part.slice(1,-1)}</code>;if(part.startsWith('**')&&part.endsWith('**'))return <strong key={i}>{part.slice(2,-2)}</strong>;const link=part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);if(link&&/^(https?:\/\/|mailto:|\/|#)/i.test(link[2]))return <a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;return <Fragment key={i}>{part}</Fragment>;});}
export function Markdown({text}:{text:string}){
  const lines=text.replace(/\r\n/g,'\n').split('\n');const nodes:ReactNode[]=[];
  for(let i=0;i<lines.length;i++){
    const line=lines[i];if(!line.trim())continue;
    if(line.startsWith('```')){const language=line.slice(3);const body:string[]=[];while(i+1<lines.length&&!lines[i+1].startsWith('```'))body.push(lines[++i]);if(i+1<lines.length)i++;const code=body.join('\n');nodes.push(<div className="code-block" key={i}><div className="code-heading"><span>{language||'代码'}</span><button title="复制代码" onClick={()=>navigator.clipboard?.writeText(code)}><Icon name="copy" size={14}/></button></div><pre><code>{code}</code></pre></div>);continue;}
    if(/^#{1,6}\s/.test(line)){nodes.push(<h3 key={i}>{inline(line.replace(/^#{1,6}\s/,''))}</h3>);continue;}
    if(/^\s*[-*]\s/.test(line)||/^\d+\.\s/.test(line)){const items:string[]=[];const ordered=/^\d+\./.test(line);do{items.push(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/,''));if(i+1>=lines.length||!/^\s*(?:[-*]|\d+\.)\s+/.test(lines[i+1]))break;i++;}while(true);nodes.push(ordered?<ol key={i}>{items.map((x,k)=><li key={k}>{inline(x)}</li>)}</ol>:<ul key={i}>{items.map((x,k)=><li key={k}>{inline(x)}</li>)}</ul>);continue;}
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){const cells=(s:string)=>s.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());const head=cells(line);i++;const rows:string[][]=[];while(i+1<lines.length&&lines[i+1].includes('|'))rows.push(cells(lines[++i]));nodes.push(<div className="table-scroll" key={i}><table><thead><tr>{head.map((x,k)=><th key={k}>{inline(x)}</th>)}</tr></thead><tbody>{rows.map((row,k)=><tr key={k}>{row.map((x,j)=><td key={j}>{inline(x)}</td>)}</tr>)}</tbody></table></div>);continue;}
    if(line.startsWith('>')){nodes.push(<blockquote key={i}>{inline(line.replace(/^>\s?/,''))}</blockquote>);continue;}
    const paragraph=[line];while(i+1<lines.length&&lines[i+1].trim()&&!/^(#{1,6}\s|```|\s*[-*]\s|\d+\.\s|>)/.test(lines[i+1]))paragraph.push(lines[++i]);nodes.push(<p key={i}>{inline(paragraph.join('\n'))}</p>);
  }
  return <div className="markdown">{nodes}</div>;
}
