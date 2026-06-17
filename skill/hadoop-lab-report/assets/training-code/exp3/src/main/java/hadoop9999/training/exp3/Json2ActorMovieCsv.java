package hadoop9999.training.exp3;

import com.alibaba.fastjson.JSON;

import java.io.*;

/**
 * P4:把 Film.json 里「我的演员」参演的电影筛出,转成 CSV(ActorMovie.csv)。
 * CSV 每行:film_page(ID),title,star,year —— 后续在 Hive 里按 year 统计「上映数量 + 平均分」,再做可视化。
 * 占位:ACTOR="我的演员" 由 prepare_training_project.py 替换为本人分配到的演员姓名。
 * 输出 ActorMovie.csv 落在 Film.json 同目录(classpath 的 resources 目录)。
 */
public class Json2ActorMovieCsv {
    //演员姓名
    private final static String ACTOR="我的演员";
    private final static String RESOURCE_DIR= new File(Json2ActorMovieCsv.class.getClassLoader().getResource("Film.json").getPath()).getParent();

    public static void main(String[] args) throws IOException {
        //获取Film.json的路径
        String filmJsonPath= Json2ActorMovieCsv.class.getClassLoader().getResource("Film.json").getPath();
        //读取Film.json
        BufferedReader br=new BufferedReader(new FileReader(filmJsonPath));
        //写到哪个文件
        FileWriter sw=new FileWriter(new File(RESOURCE_DIR,"ActorMovie.csv"));
        //MovieInfo 类可以参考实验1
        MovieInfo m=null;
        String line;
        while((line=br.readLine())!=null){
            //Fastjson 把每行的json 字符串转换为对象。
            m= JSON.parseObject(line,MovieInfo.class);
            //过滤出我的演员的电影
            if(m.getActor().indexOf(ACTOR)!=-1){
                //Film_page 作为电影ID
                String mid=m.getFilm_page();
                //把电影数据写入csv文件。csv 表头为 ID,电影名称,评分,年份
                sw.append(mid+","+m.getTitle()+","+m.getStar()+","+m.getYear()+"\n");
            }
        }
        sw.close();
        br.close();
    }
}
