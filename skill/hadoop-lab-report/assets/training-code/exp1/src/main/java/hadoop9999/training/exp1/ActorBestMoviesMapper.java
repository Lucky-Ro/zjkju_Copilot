package hadoop9999.training.exp1;

import com.alibaba.fastjson.JSON;
import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.apache.hadoop.io.LongWritable;
import org.apache.hadoop.io.NullWritable;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Mapper;

import java.io.IOException;

/**
 * 逐行读 Film.json,只保留「我的演员」参演的电影,把 MovieInfo 作为 K2 写出。
 * 占位:"我的演员" 由 prepare_training_project.py 替换为本人分配到的演员姓名。
 */
public class ActorBestMoviesMapper extends Mapper<LongWritable, Text, MovieInfo, NullWritable>{

	 public static final Log log = LogFactory.getLog(ActorBestMoviesMapper.class);

	@Override
	protected void map(LongWritable key1, Text value1, Context context)
	throws IOException, InterruptedException {
		String val=value1.toString();
		MovieInfo m=JSON.parseObject(val, MovieInfo.class);
		if(m.getActorSet().contains("我的演员")){
			log.info(m.getTitle());
			context.write(m, NullWritable.get());
		}

	}
}
