package hadoop9999.training.exp2;

import com.alibaba.fastjson.JSON;

import java.io.*;

/**
 * P3:把 Film.json 里「我的演员」参演的电影,按「一部电影的每个演员一行」展开成 CSV(CoActor.csv)。
 * CSV 每行:film_page(ID),title,actor,star,year —— 这样在 Hive 里统计某演员合作次数=统计其出现次数。
 * 占位:ACTOR="我的演员" 由 prepare_training_project.py 替换为本人分配到的演员姓名。
 * 输出 CoActor.csv 落在 Film.json 同目录(classpath 的 resources 目录)。
 */
public class Json2CoActorCsv {
    //演员姓名
    private final static String ACTOR="我的演员";
    private final static String RESOURCE_DIR= new File(Json2CoActorCsv.class.getClassLoader().getResource("Film.json").getPath()).getParent();

    public static void main(String[] args) throws IOException {
        //获取Film.json的路径
        String filmJsonPath= Json2CoActorCsv.class.getClassLoader().getResource("Film.json").getPath();
        //读取Film.json
        BufferedReader br=new BufferedReader(new FileReader(filmJsonPath));
        //写到哪个文件
        FileWriter sw=new FileWriter(new File(RESOURCE_DIR,"CoActor.csv"));
        //MovieInfo 类可以参考实验1
        MovieInfo m=null;
        String line;
        while((line=br.readLine())!=null){
            //Fastjson 把每行的json 字符串转换为对象。
            m= JSON.parseObject(line,MovieInfo.class);
            //过滤并把每部电影合作的每个演员，都转为包含电影信息1行csv数据
            if(m.getActor().indexOf(ACTOR)!=-1){
                //Film_page 作为电影ID
                String mid=m.getFilm_page();
                //取出演员的列表
                String[] actors=m.getActor().split(",");
                for(String ac:actors){
                    //把电影数据写入csv文件。csv 表头为 ID,电影名称,演员,评分,年份
                    sw.append(mid+","+m.getTitle()+","+ac+","+m.getStar()+","+m.getYear()+"\n");
                }
            }
        }
        sw.close();
        br.close();
    }
}
